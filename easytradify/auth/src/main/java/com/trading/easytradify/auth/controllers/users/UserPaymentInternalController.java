package com.trading.easytradify.auth.controllers.users;

import com.trading.easytradify.auth.dto.user.UserPaymentInfoDto;
import com.trading.easytradify.auth.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/internal/users/payment")
@RequiredArgsConstructor
@Slf4j
public class UserPaymentInternalController {

    private final UserRepository userRepository;

    @Value("${internal.api.key}")
    private String internalApiKey;

    @GetMapping("/{userId}")
    public UserPaymentInfoDto getUserPaymentInfo(
            @PathVariable Integer userId,
            @RequestHeader("X-API-Key") String apiKey) {

        validateApiKey(apiKey);
        log.info("Payment service fetching user info for: {}", userId);

        return userRepository.findById(userId)
                .map(user -> UserPaymentInfoDto.builder()
                        .id(user.getId())
                        .email(user.getEmail())
                        .firstName(user.getFirstName())
                        .lastName(user.getLastName())
                        .numTel(user.getNumTel())
                        .build())
                .orElse(null);
    }

    private void validateApiKey(String apiKey) {
        if (apiKey == null || !apiKey.equals(internalApiKey)) {
            throw new SecurityException("Invalid API key");
        }
    }
}