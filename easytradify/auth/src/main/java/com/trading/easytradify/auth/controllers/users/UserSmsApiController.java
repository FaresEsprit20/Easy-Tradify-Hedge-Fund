package com.trading.easytradify.auth.controllers.users;

import com.trading.easytradify.auth.dto.sms.UserPhoneDto;
import com.trading.easytradify.auth.entities.enums.UserRole;
import com.trading.easytradify.auth.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.stream.Collectors;

@RestController
@RequestMapping("/internal/users/sms")
@RequiredArgsConstructor
@Slf4j
public class UserSmsApiController {

    private final UserRepository userRepository;

    @Value("${internal.api.key}")
    private String internalApiKey;

    /**
     * Get all user phone numbers
     */
    @GetMapping("/phone-numbers")
    public List<UserPhoneDto> getAllPhoneNumbers(@RequestHeader("X-API-Key") String apiKey) {
        validateApiKey(apiKey);
        log.info("Internal API: SMS service fetching all user phone numbers");

        return userRepository.findAll().stream()
                .filter(user -> user.getNumTel() != null && !user.getNumTel().isEmpty())
                .map(user -> new UserPhoneDto(user.getId(), user.getNumTel(), user.getFirstName(), user.getLastName()))
                .collect(Collectors.toList());
    }

    /**
     * Get phone numbers by role
     */
    @GetMapping("/phone-numbers/by-role")
    public List<UserPhoneDto> getPhoneNumbersByRole(
            @RequestParam UserRole role,
            @RequestHeader("X-API-Key") String apiKey) {
        validateApiKey(apiKey);
        log.info("Internal API: SMS service fetching phone numbers by role: {}", role);

        return userRepository.findAll().stream()
                .filter(user -> user.getNumTel() != null && !user.getNumTel().isEmpty())
                .filter(user -> user.getRoles().stream().anyMatch(r -> r.getRoleName().equals(role)))
                .map(user -> new UserPhoneDto(user.getId(), user.getNumTel(), user.getFirstName(), user.getLastName()))
                .collect(Collectors.toList());
    }

    /**
     * Get phone number by user email
     */
    @GetMapping("/phone-number")
    public UserPhoneDto getPhoneNumberByEmail(
            @RequestParam String email,
            @RequestHeader("X-API-Key") String apiKey) {
        validateApiKey(apiKey);
        log.info("Internal API: SMS service fetching phone number for email: {}", email);

        return userRepository.findUserByEmail(email)
                .filter(user -> user.getNumTel() != null && !user.getNumTel().isEmpty())
                .map(user -> new UserPhoneDto(user.getId(), user.getNumTel(), user.getFirstName(), user.getLastName()))
                .orElse(null);
    }

    /**
     * Get phone number by user ID
     */
    @GetMapping("/phone-number/{userId}")
    public UserPhoneDto getPhoneNumberByUserId(
            @PathVariable Integer userId,
            @RequestHeader("X-API-Key") String apiKey) {
        validateApiKey(apiKey);
        log.info("Internal API: SMS service fetching phone number for user ID: {}", userId);

        return userRepository.findById(userId)
                .filter(user -> user.getNumTel() != null && !user.getNumTel().isEmpty())
                .map(user -> new UserPhoneDto(user.getId(), user.getNumTel(), user.getFirstName(), user.getLastName()))
                .orElse(null);
    }

    private void validateApiKey(String apiKey) {
        if (apiKey == null || !apiKey.equals(internalApiKey)) {
            log.warn("Invalid internal API key from SMS service");
            throw new SecurityException("Invalid API key");
        }
    }
}