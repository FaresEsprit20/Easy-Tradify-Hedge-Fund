package com.trading.easytradify.auth.validators.email;

import com.trading.easytradify.common.utils.constants.FieldsValidation;

import java.util.ArrayList;
import java.util.List;

/**
 * Checks an email address's shape.
 *
 * <p>
 * Returns a list of problems rather than throwing or returning a boolean: the
 * callers collect these into an {@code InvalidEntityException} so the client
 * gets every reason at once instead of discovering them one submission at a
 * time.
 * </p>
 *
 * <p>
 * Shape only. A syntactically valid address may not exist, may not be
 * deliverable, and may not belong to the person supplying it — proving that is
 * what the verification email is for, and no regex substitutes for it.
 * </p>
 */
public final class EmailValidator {

    private EmailValidator() {
        // Static utility.
    }

    public static List<String> validate(String email) {
        List<String> errors = new ArrayList<>();

        if (email == null || email.isBlank()) {
            errors.add("Email is required");
            // Return early: every check below would otherwise add a second,
            // redundant complaint about the same missing value.
            return errors;
        }

        String trimmed = email.trim();

        if (trimmed.length() > FieldsValidation.MAX_EMAIL_LENGTH) {
            errors.add("Email must be at most " + FieldsValidation.MAX_EMAIL_LENGTH + " characters");
        }

        if (!trimmed.matches(FieldsValidation.EMAIL_REGEX)) {
            errors.add("Email format is invalid");
        }

        return errors;
    }
}
