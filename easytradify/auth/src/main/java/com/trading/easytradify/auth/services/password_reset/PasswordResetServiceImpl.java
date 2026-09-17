package com.trading.easytradify.auth.services.password_reset;

import com.trading.easytradify.auth.dto.password_reset.TokenVerificationResponse;
import com.trading.easytradify.auth.dto.token.PasswordResetTokenDto;
import com.trading.easytradify.auth.dto.user.UserExtendedDto;
import com.trading.easytradify.auth.entities.UnifiedToken;
import com.trading.easytradify.auth.entities.enums.TokenType;
import com.trading.easytradify.auth.repository.PasswordResetTokenRepository;
import com.trading.easytradify.auth.repository.UnifiedTokenRepository;
import com.trading.easytradify.auth.services.users.UserService;
import com.trading.easytradify.auth.validators.email.EmailValidator;
import com.trading.easytradify.auth.validators.password.PasswordValidator;
import com.trading.easytradify.common.dto.auth.ChangePasswordUserRequestDto;
import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.InvalidEntityException;
import com.trading.easytradify.common.exception.InvalidOperationException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.client.loadbalancer.LoadBalanced;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

@Service
@RequiredArgsConstructor
@Slf4j
public class PasswordResetServiceImpl implements PasswordResetService {

    private final PasswordResetTokenRepository tokenRepo;
    private final UnifiedTokenRepository unifiedTokenRepository;
    private final UserService userService;

    @LoadBalanced
    private final WebClient.Builder loadBalancedWebClientBuilder;

    @Value("${internal.api.key}")
    private String internalApiKey;

    @Value("${app.reset-url}")
    private String resetUrl;

    @Override
    public void sendResetLink(String email, String recaptchaToken, String userIp, String action) {
        List<String> errors = EmailValidator.validate(email);
        if (!errors.isEmpty()) {
            throw new InvalidEntityException("The provided Email is not Valid ",
                    ErrorCodes.INVALID_EMAIL_ERROR, errors);
        }

        UserExtendedDto optionalUser = userService.findByEmail(email);
        if (optionalUser == null) {
            throw new InvalidEntityException("The provided Email is not found / linked with any User in our DB ",
                    ErrorCodes.EMAIL_NOT_FOUND_ERROR, errors);
        }

        Optional<UnifiedToken> lastTokenOpt = tokenRepo.findTopByUserEmailOrderByCreationDateDesc(email);
        if (lastTokenOpt.isPresent()) {
            PasswordResetTokenDto lastToken = PasswordResetTokenDto.fromEntity(lastTokenOpt.get());
            LocalDateTime createdAt = lastToken.getCreationDate();
            if (createdAt != null && Duration.between(createdAt, LocalDateTime.now()).toMinutes() < 3) {
                throw new InvalidOperationException(
                        "Please wait at least 3 minutes before requesting another reset email.",
                        ErrorCodes.RATE_LIMIT_EXCEEDED, List.of("Wait 3 minutes between reset requests."));
            }
        }

        String token = UUID.randomUUID().toString();

        // Create password reset token using UnifiedToken
        UnifiedToken resetToken = UnifiedToken.builder()
                .token(token)
                .userEmail(email)
                .tokenType(TokenType.PASSWORD_RESET)
                .isUsed(false)
                .creationDate(LocalDateTime.now())
                .expirationDate(LocalDateTime.now().plusMinutes(5))
                .build();

        unifiedTokenRepository.save(resetToken);

        String link = resetUrl + "?token=" + token;

        String htmlContent = "<!DOCTYPE html>"
                + "<html>"
                + "<body>"
                + "<h2>Password Reset Request</h2>"
                + "<p>You requested to reset your password.</p>"
                + "<p><a href=\"" + link + "\">Click here to reset your password</a></p>"
                + "<p>This link will expire in 5 minutes.</p>"
                + "<p>If you didn't request this, please ignore this email.</p>"
                + "</body>"
                + "</html>";

        boolean sent = sendEmailViaMailingService(email, "Password Reset Request", htmlContent, "App Password Reset");

        if (!sent) {
            errors.clear();
            errors.add("Failed to send reset email");
            throw new InvalidOperationException("Could not send the email: ",
                    ErrorCodes.EMAIL_SERVICE_ERROR, errors);
        }
    }

    private boolean sendEmailViaMailingService(String to, String subject, String htmlContent, String label) {
        try {
            Map<String, String> request = Map.of(
                    "to", to,
                    "subject", subject,
                    "content", htmlContent,
                    "label", label
            );

            // Use service discovery - call by SERVICE NAME, not localhost
            Map<String, Object> response = loadBalancedWebClientBuilder.build()
                    .post()
                    .uri("http://mailing-service/internal/email/send-html")
                    .header("X-API-Key", internalApiKey)
                    .bodyValue(request)
                    .retrieve()
                    .bodyToMono(Map.class)
                    .block();

            return response != null && Boolean.TRUE.equals(response.get("success"));

        } catch (Exception e) {
            log.error("Failed to send email via mailing service: {}", e.getMessage());
            return false;
        }
    }

    @Override
    public boolean resetPassword(String token, ChangePasswordUserRequestDto newPassword) {
        List<String> errors = PasswordValidator.validate(newPassword.getPassword());
        if (!errors.isEmpty()) {
            throw new InvalidEntityException("The password format is incorrect: ",
                    ErrorCodes.USER_CHANGE_PASSWORD_OBJECT_NOT_VALID, errors);
        }

        Optional<UnifiedToken> tokenOpt = tokenRepo.findByToken(token);
        PasswordResetTokenDto resetToken = tokenOpt.map(PasswordResetTokenDto::fromEntity).orElse(null);

        if (resetToken == null || resetToken.isUsed()) {
            throw new InvalidOperationException(
                    "The Reset Token is Already used: Please Generate a new one by submitting a new password reset request",
                    ErrorCodes.USER_CHANGE_PASSWORD_OBJECT_NOT_VALID, errors);
        }

        if (resetToken.getExpirationDate().isBefore(LocalDateTime.now())) {
            throw new InvalidOperationException(
                    "The Reset Token is Already expired: Please Generate a new one by submitting a new password reset request",
                    ErrorCodes.USER_CHANGE_PASSWORD_OBJECT_NOT_VALID, errors);
        }

        userService.changePassword(newPassword);

        // Update token as used - find the actual UnifiedToken and update it
        Optional<UnifiedToken> tokenToUpdate = unifiedTokenRepository.findByTokenAndType(token, TokenType.PASSWORD_RESET);
        if (tokenToUpdate.isPresent()) {
            UnifiedToken unifiedToken = tokenToUpdate.get();
            unifiedToken.setUsed(true);
            unifiedTokenRepository.save(unifiedToken);
        }

        return true;
    }

    @Override
    public boolean resendResetLink(String email, String recaptchaToken, String userIp, String action) {
        List<String> errors = EmailValidator.validate(email);
        if (!errors.isEmpty()) {
            throw new InvalidEntityException("Invalid email format",
                    ErrorCodes.INVALID_EMAIL_ERROR, errors);
        }

        UserExtendedDto user = userService.findByEmail(email);
        if (user == null) {
            return true;
        }

        tokenRepo.deleteByUserEmail(email);
        sendResetLink(email, recaptchaToken, userIp, action);
        return true;
    }

    @Override
    public TokenVerificationResponse verifyToken(String token) {
        Optional<UnifiedToken> tokenOpt = tokenRepo.findByToken(token);

        if (tokenOpt.isEmpty()) {
            return TokenVerificationResponse.builder()
                    .message("Token not found")
                    .valid(false)
                    .userId(0)
                    .remainingTimeSeconds(0L)
                    .build();
        }

        PasswordResetTokenDto resetToken = PasswordResetTokenDto.fromEntity(tokenOpt.get());

        if (resetToken.isUsed()) {
            return TokenVerificationResponse.builder()
                    .message("Token already used")
                    .valid(false)
                    .userId(0)
                    .remainingTimeSeconds(0L)
                    .build();
        }

        LocalDateTime now = LocalDateTime.now();
        LocalDateTime expiry = resetToken.getExpirationDate();

        if (expiry.isBefore(now)) {
            return TokenVerificationResponse.builder()
                    .message("Token expired")
                    .valid(false)
                    .userId(0)
                    .remainingTimeSeconds(0L)
                    .build();
        }

        long remainingTimeSeconds = Duration.between(now, expiry).getSeconds();
        String userEmail = resetToken.getUserEmail();
        Integer userId = userService.findUserIdByEmail(userEmail);

        return TokenVerificationResponse.builder()
                .message("Token is valid")
                .valid(true)
                .userId(userId)
                .remainingTimeSeconds(remainingTimeSeconds)
                .build();
    }
}