package com.trading.easytradify.auth.controllers.users;

import com.trading.easytradify.auth.dto.email.UserEmailDto;
import com.trading.easytradify.auth.entities.enums.UserRole;
import com.trading.easytradify.auth.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.stream.Collectors;

@RestController
@RequestMapping("/internal/users/mailing")
@RequiredArgsConstructor
@Slf4j
public class UserMailingInternalController {

    private final UserRepository userRepository;

    @Value("${internal.api.key}")
    private String internalApiKey;

    @GetMapping("/emails")
    public List<UserEmailDto> getAllUserEmails(@RequestHeader("X-API-Key") String apiKey) {
        validateApiKey(apiKey);
        log.info("Internal API: Mailing service fetching all user emails");

        return userRepository.findAll().stream()
                .map(user -> new UserEmailDto(user.getId(), user.getEmail(), user.getFirstName(), user.getLastName()))
                .collect(Collectors.toList());
    }

    @GetMapping("/emails/by-role")
    public List<UserEmailDto> getUserEmailsByRole(
            @RequestParam UserRole role,
            @RequestHeader("X-API-Key") String apiKey) {
        validateApiKey(apiKey);
        log.info("Internal API: Mailing service fetching user emails by role: {}", role);

        return userRepository.findAll().stream()
                .filter(user -> user.getRoles().stream().anyMatch(r -> r.getRoleName().equals(role)))
                .map(user -> new UserEmailDto(user.getId(), user.getEmail(), user.getFirstName(), user.getLastName()))
                .collect(Collectors.toList());
    }

    private void validateApiKey(String apiKey) {
        if (apiKey == null || !apiKey.equals(internalApiKey)) {
            log.warn("Invalid internal API key from mailing service");
            throw new SecurityException("Invalid API key");
        }
    }


}