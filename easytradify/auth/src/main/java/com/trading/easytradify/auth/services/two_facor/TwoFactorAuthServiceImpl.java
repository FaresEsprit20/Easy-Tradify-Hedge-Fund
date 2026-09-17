package com.trading.easytradify.auth.services.two_facor;

import com.trading.easytradify.auth.dto.token.TwoFactorAuthTokenDto;
import com.trading.easytradify.auth.entities.UnifiedToken;
import com.trading.easytradify.auth.entities.enums.TokenType;
import com.trading.easytradify.auth.repository.TwoFactorAuthRepository;
import com.trading.easytradify.auth.repository.UnifiedTokenRepository;
import com.trading.easytradify.auth.repository.UserRepository;
import com.trading.easytradify.common.exception.EntityNotFoundException;
import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.InvalidOperationException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.*;

@Service
@RequiredArgsConstructor
@Slf4j
public class TwoFactorAuthServiceImpl implements TwoFactorAuthService {

    private final TwoFactorAuthRepository twoFactorAuthRepository;
    private final UserRepository userRepository;
    private final UnifiedTokenRepository unifiedTokenRepository;
    private final WebClient.Builder webClientBuilder;

    @Value("${mailing.service.url:http://mailing-service}")
    private String mailingServiceUrl;

    @Value("${internal.api.key}")
    private String internalApiKey;

    private static final int MAX_ATTEMPTS = 3;
    private static final int OTP_VALIDITY_MINUTES = 3;
    private static final int BLOCK_DURATION_MINUTES = 50;
    private static final int RESEND_DELAY_MINUTES = 1;

    @Override
    public String generateAndSendOtp(String userEmail) {
        List<String> errors = new ArrayList<>();
        validateUserExists(userEmail, errors);
        checkIfBlocked(userEmail, errors);
        checkAlreadyAuthenticated(userEmail, errors);
        checkRecentAttempts(userEmail, errors);

        // Delete old tokens before generating a new one
        unifiedTokenRepository.deleteByUserEmailAndType(userEmail, TokenType.TWO_FACTOR);

        String verificationToken = UUID.randomUUID().toString();
        String otpCode = generateSecureOtp();

        // Create two-factor token using UnifiedToken
        UnifiedToken token = UnifiedToken.builder()
                .token(otpCode)
                .verificationToken(verificationToken)
                .userEmail(userEmail)
                .tokenType(TokenType.TWO_FACTOR)
                .expirationDate(LocalDateTime.now().plusMinutes(OTP_VALIDITY_MINUTES))
                .creationDate(LocalDateTime.now())
                .attempts(0)
                .isVerified(false)
                .isBlocked(false)
                .build();

        // Save token before sending the email
        unifiedTokenRepository.save(token);

        // Call mailing service to send 2FA email via HTTP
        boolean emailSent = sendOtpViaMailingService(userEmail, otpCode);

        if (!emailSent) {
            log.error("Failed to send OTP email to {} via mailing service", userEmail);
            throw new InvalidOperationException(
                    "Failed to send verification code",
                    ErrorCodes.EMAIL_SERVICE_ERROR,
                    List.of("Failed to send OTP email"));
        }

        return verificationToken;
    }

    private boolean sendOtpViaMailingService(String userEmail, String otpCode) {
        try {
            Map<String, String> request = Map.of(
                    "email", userEmail,
                    "otp", otpCode
            );

            Map<String, Object> response = webClientBuilder.build()
                    .post()
                    .uri(mailingServiceUrl + "/internal/email/send-2fa")
                    .header("X-API-Key", internalApiKey)
                    .bodyValue(request)
                    .retrieve()
                    .bodyToMono(Map.class)
                    .block();

            return response != null && Boolean.TRUE.equals(response.get("success"));

        } catch (WebClientResponseException e) {
            log.error("HTTP error calling mailing service: {} - {}", e.getStatusCode(), e.getResponseBodyAsString());
            return false;
        } catch (Exception e) {
            log.error("Failed to call mailing service: {}", e.getMessage());
            return false;
        }
    }

    @Override
    public boolean verifyOtp(String verificationToken, String otp) {
        if (verificationToken == null || otp == null) {
            throw new InvalidOperationException(
                    "Verification token and OTP are required",
                    ErrorCodes.TWO_FACTOR_TOKEN_INVALID,
                    List.of("Missing verification parameters"));
        }

        UnifiedToken tokenEntity = twoFactorAuthRepository.findByVerificationToken(verificationToken)
                .orElseThrow(() -> new InvalidOperationException(
                        "Invalid verification session",
                        ErrorCodes.TWO_FACTOR_TOKEN_INVALID,
                        List.of("Invalid or expired verification token")));
        TwoFactorAuthTokenDto token = TwoFactorAuthTokenDto.fromEntity(tokenEntity);

        checkIfBlocked(token.getUserEmail(), new ArrayList<>());
        validateTokenState(token, new ArrayList<>());

        if (!token.getToken().equals(otp)) {
            handleFailedVerification(token);
            return false;
        }

        token.setVerified(true);

        // Save updated token status after verification
        Optional<UnifiedToken> tokenToUpdate = unifiedTokenRepository.findByTokenAndType(token.getToken(), TokenType.TWO_FACTOR);
        if (tokenToUpdate.isPresent()) {
            UnifiedToken unifiedToken = tokenToUpdate.get();
            unifiedToken.setVerified(true);
            unifiedTokenRepository.save(unifiedToken);
        }

        log.info("OTP verification successful for user: {}", token.getUserEmail());
        return true;
    }

    private void handleFailedVerification(TwoFactorAuthTokenDto token) {
        token.setAttempts(token.getAttempts() + 1);

        if (token.getAttempts() >= MAX_ATTEMPTS) {
            token.setBlocked(true);
            token.setBlockUntil(LocalDateTime.now().plusMinutes(BLOCK_DURATION_MINUTES));
            log.warn("Account blocked for user {} due to too many failed attempts", token.getUserEmail());
        }

        // Update token with failed verification
        Optional<UnifiedToken> tokenToUpdate = unifiedTokenRepository.findByTokenAndType(token.getToken(), TokenType.TWO_FACTOR);
        if (tokenToUpdate.isPresent()) {
            UnifiedToken unifiedToken = tokenToUpdate.get();
            unifiedToken.setAttempts(unifiedToken.getAttempts() + 1);

            if (unifiedToken.getAttempts() >= MAX_ATTEMPTS) {
                unifiedToken.setBlocked(true);
                unifiedToken.setBlockUntil(LocalDateTime.now().plusMinutes(BLOCK_DURATION_MINUTES));
                log.warn("Account blocked for user {} due to too many failed attempts", unifiedToken.getUserEmail());
            }

            unifiedTokenRepository.save(unifiedToken);
        }
    }

    @Override
    public String getUserEmailByVerificationToken(String verificationToken) {
        UnifiedToken tokenEntity = twoFactorAuthRepository.findByVerificationToken(verificationToken)
                .orElseThrow(() -> new InvalidOperationException(
                        "Invalid verification token",
                        ErrorCodes.TWO_FACTOR_TOKEN_INVALID,
                        List.of("Invalid verification token")));
        return tokenEntity.getUserEmail();
    }

    @Override
    public String resendOtp(String userEmail) {
        List<String> errors = new ArrayList<>();
        validateUserExists(userEmail, errors);
        checkIfBlocked(userEmail, errors);
        checkAlreadyAuthenticated(userEmail, errors);
        checkRecentAttempts(userEmail, errors);

        // Delete old tokens before resending
        unifiedTokenRepository.deleteByUserEmailAndType(userEmail, TokenType.TWO_FACTOR);

        return generateAndSendOtp(userEmail);
    }

    @Override
    public Map<String, Long> getTimingInfo(String userEmail) {
        Map<String, Long> timingInfo = new HashMap<>();
        unifiedTokenRepository.findTopTwoFactorTokenByUserEmailOrderByCreationDateDesc(userEmail)
                .ifPresent(token -> {
                    TwoFactorAuthTokenDto dto = TwoFactorAuthTokenDto.fromEntity(token);
                    LocalDateTime now = LocalDateTime.now();
                    timingInfo.put("resendAllowedInSeconds",
                            Math.max(0, Duration.between(now, dto.getCreationDate().plusMinutes(RESEND_DELAY_MINUTES)).getSeconds()));
                    timingInfo.put("otpValidForSeconds",
                            Math.max(0, Duration.between(now, dto.getExpirationDate()).getSeconds()));
                });
        return timingInfo;
    }

    @Override
    public void clearExpiredTokens() {
        LocalDateTime now = LocalDateTime.now();
        List<UnifiedToken> expiredTokens = twoFactorAuthRepository.findByExpirationDateBefore(now);
        if (!expiredTokens.isEmpty()) {
            // Delete expired tokens
            for (UnifiedToken expiredToken : expiredTokens) {
                unifiedTokenRepository.deleteByVerificationToken(expiredToken.getVerificationToken());
            }
            log.debug("Cleared {} expired OTP tokens", expiredTokens.size());
        }
    }

    @Scheduled(cron = "0 */5 * * * ?")
    @Override
    @Transactional
    public void scheduledTokenCleanup() {
        clearExpiredTokens();
    }

    private void validateUserExists(String userEmail, List<String> errors) {
        if (!userRepository.existsByEmail(userEmail)) {
            errors.add("User not found");
            throw new EntityNotFoundException(
                    "User with email " + userEmail + " not found",
                    ErrorCodes.USER_NOT_FOUND,
                    errors);
        }
    }

    private String generateSecureOtp() {
        return String.format("%06d", new Random().nextInt(999999));
    }

    private void validateTokenState(TwoFactorAuthTokenDto token, List<String> errors) {
        if (token.getExpirationDate().isBefore(LocalDateTime.now())) {
            errors.add("Expired OTP");
            throw new InvalidOperationException(
                    "Verification code has expired",
                    ErrorCodes.TWO_FACTOR_TOKEN_EXPIRED,
                    errors);
        }

        if (token.isVerified()) {
            errors.add("Code already used");
            throw new InvalidOperationException(
                    "Verification code was already used",
                    ErrorCodes.TWO_FACTOR_TOKEN_ALREADY_USED,
                    errors);
        }

        if (token.isBlocked() && token.getBlockUntil() != null && token.getBlockUntil().isAfter(LocalDateTime.now())) {
            errors.add("Account temporarily blocked");
            throw new InvalidOperationException(
                    "Account temporarily blocked due to too many attempts",
                    ErrorCodes.TWO_FACTOR_ACCOUNT_BLOCKED,
                    errors);
        }
    }

    private void checkIfBlocked(String userEmail, List<String> errors) {
        unifiedTokenRepository.findTopTwoFactorTokenByUserEmailOrderByCreationDateDesc(userEmail)
                .ifPresent(token -> {
                    TwoFactorAuthTokenDto dto = TwoFactorAuthTokenDto.fromEntity(token);
                    if (dto.isBlocked() && dto.getBlockUntil() != null && dto.getBlockUntil().isAfter(LocalDateTime.now())) {
                        errors.add("Account blocked");
                        throw new InvalidOperationException(
                                "Account temporarily blocked",
                                ErrorCodes.TWO_FACTOR_ACCOUNT_BLOCKED,
                                errors);
                    }
                });
    }

    private void checkAlreadyAuthenticated(String userEmail, List<String> errors) {
        unifiedTokenRepository.findTopTwoFactorTokenByUserEmailOrderByCreationDateDesc(userEmail)
                .ifPresent(token -> {
                    TwoFactorAuthTokenDto dto = TwoFactorAuthTokenDto.fromEntity(token);
                    if (dto.isVerified()) {
                        errors.add("Already authenticated");
                        throw new InvalidOperationException(
                                "Authentication already completed",
                                ErrorCodes.TWO_FACTOR_ALREADY_AUTHENTICATED,
                                errors);
                    }
                });
    }

    private void checkRecentAttempts(String userEmail, List<String> errors) {
        unifiedTokenRepository.findTopTwoFactorTokenByUserEmailOrderByCreationDateDesc(userEmail)
                .ifPresent(token -> {
                    TwoFactorAuthTokenDto dto = TwoFactorAuthTokenDto.fromEntity(token);
                    if (dto.getCreationDate().isAfter(LocalDateTime.now().minusMinutes(RESEND_DELAY_MINUTES))) {
                        errors.add("Resend too soon");
                        throw new InvalidOperationException(
                                "Please wait before requesting a new OTP",
                                ErrorCodes.TWO_FACTOR_RESEND_LIMIT,
                                errors);
                    }
                });
    }


}