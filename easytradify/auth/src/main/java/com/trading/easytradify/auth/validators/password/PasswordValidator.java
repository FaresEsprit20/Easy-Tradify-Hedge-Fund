package com.trading.easytradify.auth.validators.password;

import com.trading.easytradify.common.utils.constants.FieldsValidation;

import java.util.ArrayList;
import java.util.List;

/**
 * Enforces the password policy.
 *
 * <p>
 * The individual reasons are reported separately rather than as one "password
 * does not meet requirements" line. A user told only that their password is
 * wrong tends to make a small change and try again; a user told it needs a
 * digit adds one.
 * </p>
 */
public final class PasswordValidator {

    private PasswordValidator() {
        // Static utility.
    }

    public static List<String> validate(String password) {
        List<String> errors = new ArrayList<>();

        if (password == null || password.isBlank()) {
            errors.add("Password is required");
            return errors;
        }

        if (password.length() < FieldsValidation.MIN_PASSWORD_LENGTH) {
            errors.add("Password must be at least " + FieldsValidation.MIN_PASSWORD_LENGTH + " characters");
        }

        if (password.length() > FieldsValidation.MAX_PASSWORD_LENGTH) {
            // Not cosmetic: BCrypt silently truncates input beyond 72 bytes, so
            // an unbounded password is not as strong as it looks.
            errors.add("Password must be at most " + FieldsValidation.MAX_PASSWORD_LENGTH + " characters");
        }

        // The composition rule is checked separately from length so that a
        // password failing both is told about both.
        if (!password.matches(FieldsValidation.PASSWORD_REGEX)) {
            errors.add("Password must contain an uppercase letter, a lowercase letter, a digit and a special character (@$!%*?&-)");
        }

        return errors;
    }
}
