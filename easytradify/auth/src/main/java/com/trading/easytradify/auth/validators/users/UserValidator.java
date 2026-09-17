package com.trading.easytradify.auth.validators.users;

import com.trading.easytradify.auth.dto.address.AddressDto;
import com.trading.easytradify.auth.dto.user.UserDto;
import com.trading.easytradify.auth.validators.email.EmailValidator;
import com.trading.easytradify.auth.validators.password.PasswordValidator;
import com.trading.easytradify.common.utils.constants.FieldsValidation;

import java.util.ArrayList;
import java.util.List;

/**
 * Validates a user at REGISTRATION, when every required field must be present.
 *
 * <p>
 * Kept distinct from {@link UserUpdateValidator} because the two answer
 * different questions. Registration asks "is this a complete, usable account?"
 * — and so requires a password. An update asks "are the supplied fields
 * acceptable?" and must tolerate absent ones, since a user editing their phone
 * number does not resubmit their password.
 * </p>
 */
public final class UserValidator {

    private UserValidator() {
        // Static utility.
    }

    public static List<String> validate(UserDto dto) {
        List<String> errors = new ArrayList<>();

        if (dto == null) {
            errors.add("User is required");
            return errors;
        }

        errors.addAll(EmailValidator.validate(dto.getEmail()));

        // Required here and only here — an OAuth2-created account gets a random
        // one assigned rather than going through this path.
        errors.addAll(PasswordValidator.validate(dto.getPassword()));

        errors.addAll(validateName("First name", dto.getFirstName(),
                FieldsValidation.MIN_FIRST_NAME_LENGTH, FieldsValidation.MAX_FIRST_NAME_LENGTH,
                FieldsValidation.FIRST_NAME_REGEX));

        errors.addAll(validateName("Last name", dto.getLastName(),
                FieldsValidation.MIN_LAST_NAME_LENGTH, FieldsValidation.MAX_LAST_NAME_LENGTH,
                FieldsValidation.LAST_NAME_REGEX));

        errors.addAll(validatePhone(dto.getNumTel(), true));
        errors.addAll(validateAddress(dto.getAddress()));

        return errors;
    }

    // ----------------------------------------------------------------
    // Shared with UserUpdateValidator
    // ----------------------------------------------------------------

    static List<String> validateName(String label, String value, int min, int max, String regex) {
        List<String> errors = new ArrayList<>();

        if (value == null || value.isBlank()) {
            errors.add(label + " is required");
            return errors;
        }

        String trimmed = value.trim();
        if (trimmed.length() < min || trimmed.length() > max) {
            errors.add(label + " must be between " + min + " and " + max + " characters");
        }
        if (!trimmed.matches(regex)) {
            errors.add(label + " may only contain letters, spaces and hyphens");
        }
        return errors;
    }

    /**
     * @param required false on the update path, where an absent value means
     *                 "leave it alone" rather than "clear it"
     */
    static List<String> validatePhone(String numTel, boolean required) {
        List<String> errors = new ArrayList<>();

        if (numTel == null || numTel.isBlank()) {
            if (required) errors.add("Phone number is required");
            return errors;
        }

        // Placeholders synthesised for OAuth2 signups ("OA" + random) are
        // exempt: those accounts never supplied a number, and rejecting the
        // placeholder would block the user from updating anything at all until
        // they entered one.
        if (numTel.startsWith("OA")) {
            return errors;
        }

        if (!numTel.trim().matches(FieldsValidation.PHONE_NUMBER_REGEX)) {
            errors.add("Phone number must be 8 digits");
        }
        return errors;
    }

    /**
     * Address is optional as a whole, but internally consistent when supplied:
     * a half-filled address is worse than none, because it looks complete.
     */
    static List<String> validateAddress(AddressDto address) {
        List<String> errors = new ArrayList<>();
        if (address == null) return errors;

        if (isPresent(address.getCity())
                && !address.getCity().trim().matches(FieldsValidation.CITY_REGEX)) {
            errors.add("City may only contain letters, spaces and hyphens");
        }

        if (isPresent(address.getZipCode())
                && !address.getZipCode().trim().matches(FieldsValidation.ZIP_CODE_REGEX)) {
            errors.add("Zip code must be numeric");
        }

        if (isPresent(address.getCountry())
                && !address.getCountry().trim().matches(FieldsValidation.COUNTRY_REGEX)) {
            errors.add("Country may only contain letters and spaces");
        }

        return errors;
    }

    private static boolean isPresent(String value) {
        return value != null && !value.isBlank();
    }
}
