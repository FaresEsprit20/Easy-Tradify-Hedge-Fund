package com.trading.easytradify.auth.services.users;

import com.trading.easytradify.auth.entities.User;
import com.trading.easytradify.auth.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.UUID;

@Slf4j
@Service
@RequiredArgsConstructor
public class CustomUserDetailsService implements UserDetailsService {

    private final UserRepository userRepository;

    @Override
    public UserDetails loadUserByUsername(String login) throws UsernameNotFoundException {
        log.info("Loading user by email or username: {}", login);
        return userRepository.findUserByEmailOrUsername(login)
                .orElseThrow(() -> new UsernameNotFoundException("User not found with email or username: " + login));
    }

    /**
     * Load or create user from OAuth2 provider (Google, GitHub, etc.)
     */
    @Transactional
    public UserDetails loadUserByOAuth2Provider(String provider, String providerId, String email, String name) {
        log.info("Loading OAuth2 user from provider: {}, providerId: {}", provider, providerId);

        // Try to find existing user by provider and providerId
        return userRepository.findByProviderAndProviderId(provider, providerId)
                .map(existingUser -> {
                    log.info("Found existing OAuth2 user: {}", existingUser.getEmail());
                    // Update user info if needed (name might have changed)
                    if (name != null && !name.isEmpty()) {
                        updateUserName(existingUser, name);
                    }
                    return existingUser;
                })
                .orElseGet(() -> {
                    // Try to find by email (if user already registered with email/password)
                    return userRepository.findUserByEmail(email)
                            .map(existingUser -> {
                                log.info("Linking OAuth2 to existing user: {}", email);
                                // Link OAuth2 provider to existing user
                                existingUser.setProvider(provider);
                                existingUser.setProviderId(providerId);
                                return userRepository.save(existingUser);
                            })
                            .orElseGet(() -> {
                                // Create brand new user from OAuth2
                                log.info("Creating new user from OAuth2: {}", email);
                                return createOAuth2User(provider, providerId, email, name);
                            });
                });
    }

    /**
     * Create a new user from OAuth2 provider data
     */
    private User createOAuth2User(String provider, String providerId, String email, String name) {
        User user = new User();
        user.setProvider(provider);
        user.setProviderId(providerId);
        user.setEmail(email);
        user.setLocked(false);


        // Extract first name and last name from full name
        if (name != null && !name.isEmpty()) {
            String[] nameParts = name.split(" ", 2);
            user.setFirstName(nameParts[0]);
            if (nameParts.length > 1) {
                user.setLastName(nameParts[1]);
            }
        } else {
            // Use email prefix as name if no name provided
            String emailPrefix = email != null ? email.split("@")[0] : provider;
            user.setFirstName(emailPrefix);
            user.setLastName(provider);
        }

        // Generate a placeholder phone number (user can update later). numTel
        // is NOT NULL + UNIQUE app-wide, so this must be unique per user, not
        // a shared literal — a second OAuth2 signup would otherwise collide
        // on this exact constraint.
        user.setNumTel("OA" + UUID.randomUUID().toString().replace("-", "").substring(0, 10));

        // Generate a random secure password (user won't use it for OAuth2 login)
        user.setPassword(UUID.randomUUID().toString());

        log.info("Created new OAuth2 user: {} from provider: {}", email, provider);
        return userRepository.save(user);
    }

    /**
     * Update user's name from OAuth2 provider
     */
    private void updateUserName(User user, String name) {
        if (name != null && !name.isEmpty()) {
            String[] nameParts = name.split(" ", 2);
            String firstName = nameParts[0];
            String lastName = nameParts.length > 1 ? nameParts[1] : "";

            if (user.getFirstName() == null || user.getFirstName().isEmpty()) {
                user.setFirstName(firstName);
            }
            if ((user.getLastName() == null || user.getLastName().isEmpty()) && !lastName.isEmpty()) {
                user.setLastName(lastName);
            }
        }
    }

    /**
     * Get user by email (for token validation)
     */
    @Transactional(readOnly = true)
    public User getUserByEmail(String email) {
        return userRepository.findUserByEmail(email)
                .orElseThrow(() -> new UsernameNotFoundException("User not found with email: " + email));
    }

    /**
     * Get user by ID
     */
    @Transactional(readOnly = true)
    public User getUserById(Integer id) {
        return userRepository.findById(id)
                .orElseThrow(() -> new UsernameNotFoundException("User not found with id: " + id));
    }

    /**
     * Get user by provider and providerId
     */
    @Transactional(readOnly = true)
    public User getUserByProviderAndProviderId(String provider, String providerId) {
        return userRepository.findByProviderAndProviderId(provider, providerId)
                .orElseThrow(() -> new UsernameNotFoundException(
                        String.format("User not found with provider: %s and providerId: %s", provider, providerId)));
    }

    /**
     * Check if user exists by email
     */
    @Transactional(readOnly = true)
    public boolean existsByEmail(String email) {
        return userRepository.existsByEmail(email);
    }

    /**
     * Check if user exists by provider and providerId
     */
    @Transactional(readOnly = true)
    public boolean existsByProviderAndProviderId(String provider, String providerId) {
        return userRepository.existsByProviderAndProviderId(provider, providerId);
    }



}