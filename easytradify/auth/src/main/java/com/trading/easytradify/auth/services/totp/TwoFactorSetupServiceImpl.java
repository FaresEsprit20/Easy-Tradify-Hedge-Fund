package com.trading.easytradify.auth.services.totp;

import com.trading.easytradify.auth.dto.two_factor.TotpSetupResponseDto;
import com.trading.easytradify.auth.dto.two_factor.TotpStatusResponseDto;
import com.trading.easytradify.auth.entities.User;
import com.trading.easytradify.auth.repository.UserRepository;
import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.InvalidEntityException;
import com.trading.easytradify.common.exception.InvalidOperationException;
import com.trading.easytradify.auth.dto.two_factor.TwoFactorMethodChangeResponseDto;
import com.trading.easytradify.common.entities.enums.TwoFactorMethod;
import com.trading.easytradify.auth.services.two_facor.TwoFactorAuthService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Collections;
import java.util.List;

@Slf4j
@Service
@RequiredArgsConstructor
public class TwoFactorSetupServiceImpl implements TwoFactorSetupService {

    private final UserRepository userRepository;
    private final TotpService totpService;
    private final TwoFactorAuthService twoFactorAuthService;

    @Override
    @Transactional
    public TotpSetupResponseDto beginSetup(Authentication authentication) {
        User user = resolveUser(authentication);

        if (Boolean.TRUE.equals(user.getTwoFactorEnabled())) {
            throw new InvalidOperationException(
                    "Two-factor authentication is already enabled",
                    ErrorCodes.TOTP_ALREADY_ENABLED,
                    List.of("Disable it first to set it up again with a new device"));
        }

        String secret = totpService.generateSecret();
        user.setTotpSecret(secret);
        userRepository.save(user);

        log.info("TOTP setup started for user: {}", user.getEmail());
        return TotpSetupResponseDto.builder()
                .secret(secret)
                .otpAuthUri(totpService.buildOtpAuthUri(secret, user.getEmail()))
                .build();
    }

    @Override
    @Transactional
    public void confirmSetup(Authentication authentication, String code) {
        User user = resolveUser(authentication);

        if (user.getTotpSecret() == null) {
            throw new InvalidOperationException(
                    "No two-factor setup in progress",
                    ErrorCodes.TOTP_SETUP_NOT_STARTED,
                    List.of("Start setup first before confirming a code"));
        }

        if (!totpService.verifyCode(user.getTotpSecret(), code)) {
            throw new InvalidOperationException(
                    "Invalid authentication code",
                    ErrorCodes.TWO_FACTOR_TOKEN_INVALID,
                    List.of("The code you entered is incorrect or has expired"));
        }

        user.setTwoFactorEnabled(true);
        userRepository.save(user);
        log.info("TOTP enabled for user: {}", user.getEmail());
    }


    /**
     * Records the intended method and delivers a code through it.
     *
     * <p>Nothing about the live configuration changes here. That is the whole
     * point: email depends on a separate mailing service, and writing the new
     * method before proving it works would lock the account behind a message
     * that never arrives. The pending method is held aside until a code that
     * actually reached the user comes back.
     */
    @Override
    @Transactional
    public TwoFactorMethodChangeResponseDto startMethodChange(Authentication authentication,
                                                              TwoFactorMethod method) {
        User user = resolveUser(authentication);
        if (method == null) {
            throw new InvalidOperationException(
                    "No method specified",
                    ErrorCodes.TWO_FACTOR_TOKEN_INVALID,
                    List.of("Choose either the authenticator app or email"));
        }
        if (!Boolean.TRUE.equals(user.getTwoFactorEnabled())) {
            throw new InvalidOperationException(
                    "Two-factor authentication is not enabled",
                    ErrorCodes.TOTP_NOT_ENABLED,
                    List.of("Enable two-factor authentication before choosing how it is delivered"));
        }
        if (method == user.resolvedTwoFactorMethod()) {
            throw new InvalidOperationException(
                    "That is already your current method",
                    ErrorCodes.TWO_FACTOR_TOKEN_INVALID,
                    Collections.emptyList());
        }

        user.setPendingTwoFactorMethod(method);

        if (method == TwoFactorMethod.EMAIL) {
            boolean delivered;
            try {
                twoFactorAuthService.generateAndSendOtp(user.getEmail());
                delivered = true;
            } catch (Exception e) {
                // Reported rather than thrown: the user has lost nothing, and
                // the honest answer is "we could not send it", not a stack
                // trace or a silent "check your inbox".
                log.warn("Could not send a 2FA method-change code to {}: {}", user.getEmail(), e.getMessage());
                delivered = false;
            }
            if (!delivered) {
                user.setPendingTwoFactorMethod(null);
            }
            userRepository.save(user);
            return TwoFactorMethodChangeResponseDto.builder()
                    .pendingMethod(delivered ? method : null)
                    .codeDelivered(delivered)
                    .message(delivered
                            ? "We sent a code to " + user.getEmail() + ". Enter it to switch."
                            : "We could not send the email, so your current method is unchanged.")
                    .build();
        }

        // Moving to the authenticator app: a new secret, held on the user but
        // not yet in force, and the QR to enrol it.
        String secret = totpService.generateSecret();
        user.setTotpSecret(secret);
        userRepository.save(user);
        log.info("2FA method change to TOTP started for {}", user.getEmail());

        return TwoFactorMethodChangeResponseDto.builder()
                .pendingMethod(method)
                .secret(secret)
                .otpAuthUri(totpService.buildOtpAuthUri(secret, user.getEmail()))
                .codeDelivered(true)
                .message("Scan the code, then enter the six digits to switch.")
                .build();
    }

    /**
     * Applies a pending switch once a code from the new channel checks out.
     *
     * <p>Verified against the <em>pending</em> method, not the current one -
     * verifying against the old method would prove the user still has their
     * old device and nothing about whether the new channel reaches them.
     */
    @Override
    @Transactional
    public void confirmMethodChange(Authentication authentication, String code) {
        User user = resolveUser(authentication);
        TwoFactorMethod pending = user.getPendingTwoFactorMethod();
        if (pending == null) {
            throw new InvalidOperationException(
                    "No method change in progress",
                    ErrorCodes.TOTP_SETUP_NOT_STARTED,
                    List.of("Start a method change before confirming a code"));
        }

        boolean valid = pending == TwoFactorMethod.EMAIL
                ? twoFactorAuthService.verifyOtp(user.getEmail(), code)
                : totpService.verifyCode(user.getTotpSecret(), code);

        if (!valid) {
            throw new InvalidOperationException(
                    "Invalid authentication code",
                    ErrorCodes.TWO_FACTOR_TOKEN_INVALID,
                    List.of("The code you entered is incorrect or has expired"));
        }

        user.setTwoFactorMethod(pending);
        user.setPendingTwoFactorMethod(null);
        userRepository.save(user);
        log.info("2FA method switched to {} for {}", pending, user.getEmail());
    }

    @Override
    @Transactional
    public void disable(Authentication authentication, String code) {
        User user = resolveUser(authentication);

        if (!Boolean.TRUE.equals(user.getTwoFactorEnabled())) {
            throw new InvalidOperationException(
                    "Two-factor authentication is not enabled",
                    ErrorCodes.TOTP_NOT_ENABLED,
                    Collections.emptyList());
        }

        if (!totpService.verifyCode(user.getTotpSecret(), code)) {
            throw new InvalidOperationException(
                    "Invalid authentication code",
                    ErrorCodes.TWO_FACTOR_TOKEN_INVALID,
                    List.of("The code you entered is incorrect or has expired"));
        }

        user.setTwoFactorEnabled(false);
        user.setTotpSecret(null);
        userRepository.save(user);
        log.info("TOTP disabled for user: {}", user.getEmail());
    }

    @Override
    public TotpStatusResponseDto getStatus(Authentication authentication) {
        User user = resolveUser(authentication);
        return TotpStatusResponseDto.builder()
                .enabled(Boolean.TRUE.equals(user.getTwoFactorEnabled()))
                .method(user.resolvedTwoFactorMethod().name())
                .pendingMethod(user.getPendingTwoFactorMethod() == null
                        ? null : user.getPendingTwoFactorMethod().name())
                .build();
    }

    private User resolveUser(Authentication authentication) {
        if (authentication == null || !authentication.isAuthenticated()) {
            throw new InvalidEntityException("Not authenticated", ErrorCodes.USER_NOT_AUTHENTICATED, Collections.emptyList());
        }
        String email = authentication.getName();
        return userRepository.findUserByEmail(email)
                .orElseThrow(() -> new InvalidEntityException(
                        "User not found", ErrorCodes.USER_NOT_FOUND, Collections.singletonList("email: " + email)));
    }
}
