package com.trading.easytradify.auth.dto.token;

import com.trading.easytradify.auth.entities.UnifiedToken;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class TwoFactorAuthTokenDto {
    private Long id;
    private String token;
    private String verificationToken;
    private String userEmail;
    private LocalDateTime expirationDate;
    private LocalDateTime creationDate;
    private int attempts;
    private boolean isVerified;
    private boolean isBlocked;
    private LocalDateTime blockUntil;

    public static TwoFactorAuthTokenDto fromEntity(UnifiedToken entity) {
        if (entity == null) return null;
        return TwoFactorAuthTokenDto.builder()
                .id(entity.getId())
                .token(entity.getToken())
                .verificationToken(entity.getVerificationToken())
                .userEmail(entity.getUserEmail())
                .expirationDate(entity.getExpirationDate())
                .creationDate(entity.getCreationDate())
                .attempts(entity.getAttempts())
                .isVerified(entity.isVerified())
                .isBlocked(entity.isBlocked())
                .blockUntil(entity.getBlockUntil())
                .build();
    }
} 