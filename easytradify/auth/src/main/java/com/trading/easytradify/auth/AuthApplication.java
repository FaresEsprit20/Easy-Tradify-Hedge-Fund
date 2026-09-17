package com.trading.easytradify.auth;

import com.trading.easytradify.auth.config.security.config.DotenvInitializer;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.cloud.client.discovery.EnableDiscoveryClient;
import org.springframework.data.jpa.repository.config.EnableJpaAuditing;

/**
 * <h1>Auth Service</h1>
 * <p>
 * Owns identity for the platform: password sign-in, Google OAuth2 sign-in,
 * two-factor enrolment and verification, password reset, and account
 * management. Port <b>8089</b>.
 * </p>
 *
 * <h2>One account, two ways in</h2>
 * <p>
 * Signing in with Google and signing in with a password reach the SAME account.
 * The link is the email address: an OAuth2 login looks for an existing user by
 * {@code provider}/{@code providerId} first, then falls back to matching on
 * email and writes the provider fields onto that existing row. Without that
 * second step a user who registered with a password and later clicked "Sign in
 * with Google" would silently get a second, empty account.
 * </p>
 *
 * <h2>Opaque tokens, not JWTs</h2>
 * <p>
 * The access and refresh tokens are random opaque strings stored in
 * {@code unified_tokens} and checked against the database on every request
 * (see {@code OAuth2ResourceServer}). This costs a lookup per call and buys
 * instant revocation — signing out, or locking an account, takes effect on the
 * next request rather than whenever a signature would have expired.
 * </p>
 *
 * <h2>scanBasePackages is not set, deliberately</h2>
 * <p>
 * Every component of this service lives under {@code com.trading.easytradify.auth},
 * so the default scan of the annotated class's own package is correct and
 * complete. Adding {@code scanBasePackages} here would REPLACE that default
 * rather than extend it — the mistake that left four other modules in this
 * project with silently unregistered controllers.
 * </p>
 *
 * @author Trading Platform Team
 * @version 1.0
 */
@SpringBootApplication
@EnableDiscoveryClient
@EnableJpaAuditing
public class AuthApplication {

    public static void main(String[] args) {
        // The initializer is registered here rather than annotated, because it
        // has to run BEFORE the context refreshes — by the time beans exist,
        // the property sources it adds to have already been read.
        new SpringApplicationBuilder(AuthApplication.class)
                .initializers(new DotenvInitializer())
                .run(args);
    }
}
