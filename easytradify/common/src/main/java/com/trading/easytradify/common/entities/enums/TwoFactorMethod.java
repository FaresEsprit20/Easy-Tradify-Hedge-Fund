package com.trading.easytradify.common.entities.enums;

/**
 * How a user's second factor is delivered or verified.
 *
 * <p>
 * {@code EMAIL} sends a one-time code; {@code TOTP} verifies an authenticator
 * app's rolling code against a stored shared secret. {@code NONE} means the
 * account has no second factor — a distinct state from "not yet chosen", which
 * is why it is a value here rather than a null method field.
 * </p>
 *
 * <p>
 * TOTP is the stronger of the two: an emailed code is only as strong as the
 * mailbox it lands in, and that mailbox is often protected by the same password
 * being recovered. EMAIL remains for accounts that have not set up an
 * authenticator.
 * </p>
 */
public enum TwoFactorMethod {
    NONE,
    EMAIL,
    TOTP
}
