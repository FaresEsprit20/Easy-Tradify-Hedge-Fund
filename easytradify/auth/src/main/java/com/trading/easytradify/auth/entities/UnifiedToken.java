package com.trading.easytradify.auth.entities;

import com.trading.easytradify.auth.entities.enums.TokenType;
import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.CacheConcurrencyStrategy;

import java.time.LocalDateTime;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@Entity
@Table(name = "unified_tokens")
@org.hibernate.annotations.Cache(usage = CacheConcurrencyStrategy.NONE)
public class UnifiedToken {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(unique = true, length = 2000)
    private String token;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private TokenType tokenType;

    @Column(name = "user_email")
    private String userEmail;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id")
    private User user;

    @Column(name = "ip_hash")
    private String ipHash;

    @Column(name = "user_agent_hash")
    private String userAgentHash;

    @Column(name = "verification_token")
    private String verificationToken;

    @Column(name = "expiration_date")
    private LocalDateTime expirationDate;

    @Column(name = "creation_date")
    private LocalDateTime creationDate;

    @Column(name = "is_revoked")
    private boolean revoked;

    @Column(name = "is_expired")
    private boolean expired;

    @Column(name = "is_used")
    private boolean isUsed;

    @Column(name = "attempts")
    private int attempts;

    @Column(name = "is_verified")
    private boolean isVerified;

    @Column(name = "is_blocked")
    private boolean isBlocked;

    @Column(name = "block_until")
    private LocalDateTime blockUntil;

    @PrePersist
    protected void onCreate() {
        this.creationDate = LocalDateTime.now();

        switch (this.tokenType) {

            case OAUTH2_ACCESS:
                // OAuth2 access token - short lived (15 minutes)
                this.expirationDate = LocalDateTime.now().plusMinutes(15);
                this.revoked = false;
                this.expired = false;
                this.isUsed = false;
                break;

            case OAUTH2_REFRESH:
                // OAuth2 refresh token - long lived (7 days)
                this.expirationDate = LocalDateTime.now().plusDays(7);
                this.revoked = false;
                this.expired = false;
                this.isUsed = false;
                break;

            case PASSWORD_RESET:
                this.expirationDate = LocalDateTime.now().plusMinutes(15);
                this.isUsed = false;
                this.revoked = false;
                this.expired = false;
                break;

            case TWO_FACTOR:
                this.expirationDate = LocalDateTime.now().plusMinutes(3);
                this.attempts = 0;
                this.isVerified = false;
                this.isBlocked = false;
                this.isUsed = false;
                this.revoked = false;
                this.expired = false;
                break;

            case TOTP_LOGIN_PENDING:
                // Short-lived: the window between a correct password and a
                // correct TOTP code, not a session lifetime.
                this.expirationDate = LocalDateTime.now().plusMinutes(5);
                this.isUsed = false;
                this.revoked = false;
                this.expired = false;
                break;

            default:
                this.expirationDate = LocalDateTime.now().plusHours(1);
                this.revoked = false;
                this.expired = false;
                this.isUsed = false;
                break;
        }
    }
}