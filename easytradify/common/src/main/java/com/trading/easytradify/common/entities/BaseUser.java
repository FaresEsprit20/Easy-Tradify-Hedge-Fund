package com.trading.easytradify.common.entities;

import com.trading.easytradify.common.entities.embedded.Address;
import com.trading.easytradify.common.entities.enums.TwoFactorMethod;
import jakarta.persistence.Column;
import jakarta.persistence.Embedded;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.MappedSuperclass;
import lombok.Data;
import lombok.EqualsAndHashCode;
import lombok.NoArgsConstructor;

import java.time.LocalDate;

/**
 * The identity and profile half of a user account.
 *
 * <p>
 * Split from {@code User} so that the persistent fields live apart from the
 * Spring Security wiring: {@code User} adds roles, tokens and the
 * {@code UserDetails} implementation, and everything here is plain profile
 * state. {@code @MappedSuperclass} means these columns land on the
 * {@code users} table rather than a table of their own.
 * </p>
 *
 * <h2>Local and federated accounts are the same row</h2>
 * <p>
 * There is no separate table for Google sign-ins. A user who registered with a
 * password and later signs in with Google gets {@code provider} and
 * {@code providerId} written onto their EXISTING row, matched by email — see
 * {@code CustomUserDetailsService.loadUserByOAuth2Provider}. That is what makes
 * "sign in with Google" and "sign in with the password" reach one account
 * instead of silently creating a second one holding half the user's history.
 * </p>
 *
 * <p>
 * The corollary is that {@code email} is the identity key and must be trusted.
 * Google asserts a verified address; a provider that does not verify email
 * would let someone claim an existing account by signing up with its address,
 * so any new provider added here needs that checked before it is enabled.
 * </p>
 */
@Data
@NoArgsConstructor
@EqualsAndHashCode(callSuper = true)
@MappedSuperclass
public class BaseUser extends AbstractEntity {

    @Column(name = "first_name")
    private String firstName;

    @Column(name = "last_name")
    private String lastName;

    /**
     * The account's identity, and the key OAuth2 linking matches on.
     * Unique and required — see the class note.
     */
    @Column(nullable = false, unique = true)
    private String email;

    /**
     * Optional display/login name.
     *
     * <p>
     * Nullable on purpose, and callers must write null rather than "" when it
     * is absent: this column is unique, and Postgres treats each NULL as
     * distinct while every "" collides with every other "". Storing the empty
     * string here means the second user without a username fails to insert.
     * </p>
     */
    @Column(name = "login_name", unique = true)
    private String loginName;

    /**
     * BCrypt hash — never a plaintext password.
     *
     * <p>
     * OAuth2-only accounts still get a value here: a random UUID they will
     * never use. Leaving it null would make the column nullable and remove the
     * database's guarantee that no account exists without one.
     * </p>
     */
    @Column(nullable = false)
    private String password;

    /**
     * Phone number. Unique app-wide, which is why OAuth2 signups synthesise a
     * per-user placeholder rather than sharing one literal — a shared default
     * makes the second federated signup fail on this constraint.
     */
    @Column(name = "num_tel", unique = true)
    private String numTel;

    @Column(name = "birth_date")
    private LocalDate birthDate;

    @Column(length = 1000)
    private String photo;

    @Embedded
    private Address address;

    // ================================================================
    // FEDERATED IDENTITY
    // ================================================================

    /** "google", "github", ... — null for password-only accounts. */
    @Column(name = "provider")
    private String provider;

    /** The provider's own subject id. Stable across email changes there. */
    @Column(name = "provider_id")
    private String providerId;

    // ================================================================
    // ACCOUNT STATE
    // ================================================================

    /**
     * Boxed rather than primitive so that "never set" is distinguishable from
     * "explicitly not locked" on rows written before this column existed.
     * {@code User.isAccountNonLocked()} reads it null-safely.
     */
    @Column(name = "is_locked")
    private Boolean locked = false;

    // ================================================================
    // TWO-FACTOR
    // ================================================================

    @Column(name = "two_factor_enabled")
    private Boolean twoFactorEnabled = false;

    @Enumerated(EnumType.STRING)
    @Column(name = "two_factor_method")
    private TwoFactorMethod twoFactorMethod;

    /**
     * A method chosen but not yet proven.
     *
     * <p>
     * Held separately from {@code twoFactorMethod} so that starting a TOTP
     * setup does not switch the account over to it. Enrolment only completes
     * when a generated code verifies; until then the live method is unchanged.
     * Without this split, a user who scanned the QR code and then lost the
     * device would be locked out by a factor they never confirmed.
     * </p>
     */
    @Enumerated(EnumType.STRING)
    @Column(name = "pending_two_factor_method")
    private TwoFactorMethod pendingTwoFactorMethod;

    /**
     * Base32 shared secret for TOTP.
     *
     * <p>
     * Stored in plaintext, which is a real and deliberate limitation: anyone
     * with read access to this column can generate valid codes for any enrolled
     * user, so it is no stronger than the database itself. Encrypting it at
     * rest with a key held outside the database is the correct next step if
     * this module ever holds accounts that matter.
     * </p>
     */
    @Column(name = "totp_secret", length = 512)
    private String totpSecret;

    /**
     * The second factor actually in force, resolved rather than read raw.
     *
     * <p>
     * Never returns null, so callers can use it in a switch or call
     * {@code .name()} without a guard. {@code twoFactorMethod} on its own can
     * be null on two quite different kinds of row, and treating both as "no
     * 2FA" would let an enrolled user past the check:
     * </p>
     *
     * <ul>
     *   <li><b>Legacy enrolments.</b> Rows written before the method column
     *       existed have a {@code totpSecret} and no method. They are
     *       authenticator users and must resolve to {@code TOTP}.</li>
     *   <li><b>Enabled without an authenticator.</b> 2FA is on but no secret
     *       was ever stored, so an emailed code is the only factor that can
     *       actually be delivered — {@code EMAIL}.</li>
     * </ul>
     *
     * <p>
     * Only when 2FA is off does this report {@code NONE}.
     * </p>
     */
    public TwoFactorMethod resolvedTwoFactorMethod() {
        if (twoFactorMethod != null) {
            return twoFactorMethod;
        }
        if (!Boolean.TRUE.equals(twoFactorEnabled)) {
            return TwoFactorMethod.NONE;
        }
        return (totpSecret != null && !totpSecret.isBlank())
                ? TwoFactorMethod.TOTP
                : TwoFactorMethod.EMAIL;
    }
}
