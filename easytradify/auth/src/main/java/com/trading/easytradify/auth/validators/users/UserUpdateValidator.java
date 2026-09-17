package com.trading.easytradify.auth.validators.users;

import com.trading.easytradify.auth.dto.user.UserUpdateDto;
import com.trading.easytradify.auth.validators.email.EmailValidator;
import com.trading.easytradify.common.utils.constants.FieldsValidation;

import java.util.ArrayList;
import java.util.List;

/**
 * Validates a profile edit.
 *
 * <p>
 * Every field is optional here — an absent value means "unchanged", not
 * "clear this". That is the whole difference from {@link UserValidator}:
 * applying registration rules to an update would reject a request to change
 * one field because the other five were not resubmitted.
 * </p>
 *
 * <p>
 * Email is the exception. It is the key OAuth2 account-linking matches on, so
 * when it IS supplied it must be valid; a malformed one here does not merely
 * look untidy, it detaches the account from its federated identity.
 * </p>
 */
public final class UserUpdateValidator {

    private UserUpdateValidator() {
        // Static utility.
    }

    public static List<String> validate(UserUpdateDto dto) {
        List<String> errors = new ArrayList<>();

        if (dto == null) {
            errors.add("Update payload is required");
            return errors;
        }

        if (dto.getEmail() != null && !dto.getEmail().isBlank()) {
            errors.addAll(EmailValidator.validate(dto.getEmail()));
        }

        if (dto.getFirstName() != null && !dto.getFirstName().isBlank()) {
            errors.addAll(UserValidator.validateName("First name", dto.getFirstName(),
                    FieldsValidation.MIN_FIRST_NAME_LENGTH, FieldsValidation.MAX_FIRST_NAME_LENGTH,
                    FieldsValidation.FIRST_NAME_REGEX));
        }

        if (dto.getLastName() != null && !dto.getLastName().isBlank()) {
            errors.addAll(UserValidator.validateName("Last name", dto.getLastName(),
                    FieldsValidation.MIN_LAST_NAME_LENGTH, FieldsValidation.MAX_LAST_NAME_LENGTH,
                    FieldsValidation.LAST_NAME_REGEX));
        }

        errors.addAll(UserValidator.validatePhone(dto.getNumTel(), false));
        errors.addAll(UserValidator.validateAddress(dto.getAddress()));

        return errors;
    }
}
