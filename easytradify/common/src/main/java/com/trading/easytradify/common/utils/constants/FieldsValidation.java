package com.trading.easytradify.common.utils.constants;

import java.math.BigDecimal;

public class FieldsValidation {

    // Address Validation
    public static final int MIN_ADDRESS_LENGTH = 5;
    public static final int MAX_ADDRESS_LENGTH = 255;
    public static final String ADDRESS_CONTENT_REGEX = "^[a-zA-Z0-9\\s,.-/#]+$";

    // City Validation
    public static final int MIN_CITY_LENGTH = 2;
    public static final int MAX_CITY_LENGTH = 20;
    public static final String CITY_REGEX = "^[a-zA-ZÀ-ÿ\\s-]+$";

    // Zip Code Validation
    public static final int MIN_ZIPCODE_LENGTH = 4;
    public static final int MAX_ZIPCODE_LENGTH = 4;
    public static final String ZIP_CODE_REGEX = "^\\d+$";

    // Country Validation
    public static final int MIN_COUNTRY_LENGTH = 2;
    public static final int MAX_COUNTRY_LENGTH = 20;
    public static final String COUNTRY_REGEX = "^[a-zA-ZÀ-ÿ\\s]+$";


    // Code Validation
    public static final int MIN_CODE_LENGTH = 16;
    public static final int MAX_CODE_LENGTH = 17;
    public static final String CODE_REGEX = "^[a-zA-Z0-9_]+$";
    // Only alphanumeric characters and dashes

    // EAN-13 Barcode Validation
    public static final int EAN13_LENGTH = 13;
    public static final String EAN13_REGEX = "^\\d{13}$";
    // Exactly 13 digits for EAN-13 barcode

    // Designation Validation
    public static final int MIN_DESIGNATION_LENGTH = 3;
    public static final int MAX_DESIGNATION_LENGTH = 70;
    public static final String DESIGNATION_REGEX = "^[a-zA-ZÀ-ÿ\s-]+$";

    // First Name Validation
    public static final int MIN_FIRST_NAME_LENGTH = 2;
    public static final int MAX_FIRST_NAME_LENGTH = 20;
    public static final String FIRST_NAME_REGEX = "^[a-zA-ZÀ-ÿ\\s-]+$";

    // Last Name Validation
    public static final int MIN_LAST_NAME_LENGTH = 2;
    public static final int MAX_LAST_NAME_LENGTH = 20;
    public static final String LAST_NAME_REGEX = "^[a-zA-ZÀ-ÿ\\s-]+$";

    // Email Validation
    public static final String EMAIL_REGEX = "^[\\w-\\.]+@([\\w-]+\\.)+[\\w-]{2,4}$";

    // Phone Number Validation
    public static final String PHONE_NUMBER_REGEX = "^[0-9]{8}$";
    // Assuming phone number should be 8 digits

    // Order Lines Validation
    public static final int MIN_ORDER_LINES = 1;  // At least one order line
    public static final int MAX_ORDER_LINES = 100;  // A maximum of 100 order lines


    // Customer Order Line Validation
    public static final BigDecimal MIN_QUANTITY = BigDecimal.ONE;  // Minimum quantity should be at least 1
    public static final BigDecimal MAX_QUANTITY = new BigDecimal(10000);  // Maximum quantity limit
    public static final BigDecimal MIN_UNIT_PRICE = BigDecimal.ZERO;  // Unit price should not be negative


    // Enterprise Validation
    public static final int MIN_NAME_LENGTH = 2;  // Minimum length for the enterprise name
    public static final int MAX_NAME_LENGTH = 100;  // Maximum length for the enterprise name
    public static final int MIN_CODE_FISCAL_LENGTH = 5;  // Minimum length for the fiscal code
    public static final int MAX_CODE_FISCAL_LENGTH = 20;  // Maximum length for the fiscal code
    public static final int MAX_EMAIL_LENGTH = 100;  // Maximum length for the email
    public static final int MAX_TEL_LENGTH = 8;  // Maximum length for the telephone number
    public static final int MAX_WEBSITE_LENGTH = 500;  // Maximum length for the website


    // AuthenticationRequest validation constraints
    public static final int MIN_LOGIN_LENGTH = 5;
    public static final int MAX_LOGIN_LENGTH = 50;
    public static final int MIN_PASSWORD_LENGTH = 8;
    public static final int MAX_PASSWORD_LENGTH = 100;

    // Regex patterns for login and password
    public static final String LOGIN_REGEX = "^[a-zA-Z0-9_-]{5,50}$"; // Alphanumeric, underscores, and hyphens
    public static final String PASSWORD_REGEX
            = "^(?=.*[a-z])(?=.*[A-Z])(?=.*\\d)(?=.*[@$!%*?&\\-]).{8,100}$"; // At least one uppercase, one lowercase, one number, and one special character

    // Photo URL pattern if applicable (you can adjust the regex based on your needs)
    public static final String PHOTO_URL_REGEX = "^(https?://.*\\.(?:png|jpg|jpeg|gif))$";

    // Comment Validation
    public static final int MIN_COMMENT_LENGTH = 5;  // Minimum length of a comment
    public static final int MAX_COMMENT_LENGTH = 500; // Maximum length of a comment

    // Date must follow ISO8601 format (example: "2023-04-14T12:34:56.789Z")
    public static final String DATE_REGEX = "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$";



}
