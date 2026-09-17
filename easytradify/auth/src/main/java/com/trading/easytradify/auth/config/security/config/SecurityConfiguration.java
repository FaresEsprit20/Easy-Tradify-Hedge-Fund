package com.trading.easytradify.auth.config.security.config;

import com.trading.easytradify.auth.config.security.filters.InputSanitizerFilter;
import com.trading.easytradify.auth.config.security.filters.OAuth2AuthenticationFilter;
import com.trading.easytradify.auth.config.security.filters.RateLimitingFilter;
import com.trading.easytradify.auth.config.security.handler.OAuth2LoginSuccessHandler;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.annotation.Order;
import org.springframework.security.authentication.AuthenticationProvider;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.annotation.web.configurers.HeadersConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.List;

import static com.trading.easytradify.common.utils.constants.Constants.ACCOUNTS_ENDPOINT;
import static com.trading.easytradify.common.utils.constants.Constants.ALLOWED_ORIGINS;
import static com.trading.easytradify.common.utils.constants.Constants.AUTHENTICATION_ENDPOINT;

@Slf4j
@Configuration
@EnableWebSecurity
@EnableMethodSecurity(prePostEnabled = true)
@RequiredArgsConstructor
public class SecurityConfiguration {

    private final OAuth2AuthenticationFilter oauth2AuthFilter;
    private final AuthenticationProvider authProvider;
    private final RateLimitingFilter rateLimitingFilter;
    private final InputSanitizerFilter inputSanitizerFilter;
    private final OAuth2LoginSuccessHandler oAuth2LoginSuccessHandler;
    private final OAuth2ResourceServer oAuth2ResourceServer;

    // Composed from the endpoint constants, not spelled out. The originals were
    // literals rooted at the source project's own path; a literal that no
    // controller serves does not fail loudly -- it just silently protects
    // nothing, and the endpoint it was meant to open starts returning 401.
    //
    // The two "/stocks/..." entries from the source are dropped: they belonged
    // to that project's market-data service and have no counterpart here.
    private static final String[] WHITE_LIST = {
            "/" + AUTHENTICATION_ENDPOINT + "/**",
            "/" + ACCOUNTS_ENDPOINT + "/**",
            "/v3/api-docs/**",
            "/swagger-ui/**",
            "/swagger-ui.html",
            "/oauth2/**",
            "/users/logout",
            "/login/oauth2/**"
    };

    private static final String[] INTERNAL_WHITE_LIST = {
            "/internal/**"
    };

    @Bean
    @Order(1)
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http
                .cors(cors -> cors.configurationSource(corsConfigurationSource()))
                .csrf(AbstractHttpConfigurer::disable)
                .headers(headers -> headers
                        .frameOptions(HeadersConfigurer.FrameOptionsConfig::sameOrigin)
                )
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.IF_REQUIRED))

                // OAuth2 Login Configuration - THIS MUST COME FIRST
                .oauth2Login(oauth2 -> oauth2
                        .successHandler(oAuth2LoginSuccessHandler)
                        .failureHandler((request, response, exception) -> {
                            log.error("OAuth2 login failed: {}", exception.getMessage());
                            String message = exception.getMessage();
                            if (message == null) {
                                message = "authentication_failed";
                            }
                            String encodedMessage = URLEncoder.encode(message, StandardCharsets.UTF_8);
                            response.sendRedirect("/oauth2/error?error=authentication_failed&message=" + encodedMessage);
                        })
                        .permitAll()
                )

                // OAuth2 Resource Server (validates opaque tokens and loads roles)
                .oauth2ResourceServer(oauth2 -> oauth2
                        .opaqueToken(opaqueToken -> opaqueToken
                                .introspector(oAuth2ResourceServer)
                        )
                )

                // Authorization rules
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers(INTERNAL_WHITE_LIST).permitAll()
                        .requestMatchers(WHITE_LIST).permitAll()
                        .anyRequest().authenticated()
                )

                // Logout Configuration
                .logout(logout -> logout
                        .logoutUrl("/logout")
                        .permitAll()
                        .logoutSuccessHandler((request, response, authentication) -> {
                            response.setStatus(200);
                            response.setContentType("application/json");
                            response.getWriter().write("{\"success\": true, \"message\": \"Logged out successfully\"}");
                            response.getWriter().flush();
                        })
                        .invalidateHttpSession(true)
                        .clearAuthentication(true)
                        .deleteCookies("accessToken", "refreshToken", "JSESSIONID")
                )

                .authenticationProvider(authProvider)
                .addFilterBefore(oauth2AuthFilter, UsernamePasswordAuthenticationFilter.class)
                .addFilterBefore(rateLimitingFilter, OAuth2AuthenticationFilter.class)
                .addFilterBefore(inputSanitizerFilter, RateLimitingFilter.class);

        return http.build();
    }

    @Bean
    public CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration config = new CorsConfiguration();
        // The Angular dev server, and nothing else. The placeholder production
        // hosts carried over from the source project (app.myapp.com) are
        // removed rather than kept "for later": an allowed origin that nobody
        // owns is an origin an attacker can come to own, and allowCredentials
        // is true below, so a request from a permitted origin arrives with the
        // auth cookies attached.
        config.setAllowedOrigins(List.of(
                ALLOWED_ORIGINS,
                "http://127.0.0.1:4200"
        ));
        config.setAllowedMethods(Arrays.asList("GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"));
        config.setAllowedHeaders(Arrays.asList(
                "Content-Type",
                "Accept",
                "Origin",
                "X-Requested-With",
                "Authorization",
                "X-API-Key"
        ));
        config.setExposedHeaders(Arrays.asList("Content-Disposition", "Content-Type", "Authorization"));
        config.setAllowCredentials(true);
        config.setMaxAge(3600L);

        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", config);
        return source;
    }
}