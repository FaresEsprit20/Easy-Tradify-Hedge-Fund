package com.trading.easytradify.auth.config.security.config;

import io.github.cdimascio.dotenv.Dotenv;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ApplicationContextInitializer;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.core.env.ConfigurableEnvironment;
import org.springframework.core.env.MapPropertySource;
import org.springframework.core.env.MutablePropertySources;

import java.util.HashMap;
import java.util.Map;

/**
 * Loads a {@code .env} file into the environment before the context refreshes.
 *
 * <p>
 * This runs early enough that {@code @Value} and {@code spring.security.oauth2}
 * bindings can read from it, which is the point: the Google client id and
 * secret live in {@code .env} (git-ignored) rather than in
 * {@code application.properties} (committed).
 * </p>
 *
 * <p>
 * Registered via {@code META-INF/spring.factories} or on the
 * {@code SpringApplicationBuilder} — an {@code ApplicationContextInitializer}
 * cannot be a {@code @Bean}, because by the time beans are created the property
 * sources have already been consumed.
 * </p>
 */
public class DotenvInitializer implements ApplicationContextInitializer<ConfigurableApplicationContext> {

    private static final Logger log = LoggerFactory.getLogger(DotenvInitializer.class);

    /**
     * Key fragments whose VALUES must never be logged.
     *
     * <p>
     * The previous version printed every entry as {@code KEY=value} to stdout,
     * which put the OAuth2 client secret into the console and into whatever
     * collects it. Keys are safe to log and genuinely useful — knowing which
     * variables loaded is most of the debugging value — so only the values are
     * withheld.
     * </p>
     */
    private static final String[] SECRET_MARKERS = {
            "SECRET", "PASSWORD", "TOKEN", "KEY", "CREDENTIAL", "PRIVATE"
    };

    @Override
    public void initialize(ConfigurableApplicationContext applicationContext) {
        ConfigurableEnvironment environment = applicationContext.getEnvironment();
        MutablePropertySources propertySources = environment.getPropertySources();

        try {
            Dotenv dotenv = Dotenv.configure()
                    .directory("./")
                    .ignoreIfMissing()
                    .load();

            Map<String, Object> dotenvProperties = new HashMap<>();

            // DECLARED_IN_ENV_FILE, explicitly. The no-arg entries() returns the
            // .env entries PLUS the entire system environment, and the whole lot
            // then goes in via addFirst() -- which hands every system variable
            // precedence over application.properties. A 4-line .env was
            // injecting 100 properties. Nothing here wants that: the point of
            // this initializer is to load the file, and Spring already reads
            // real environment variables through its own source, at the right
            // precedence.
            dotenv.entries(Dotenv.Filter.DECLARED_IN_ENV_FILE).forEach(entry -> {
                dotenvProperties.put(entry.getKey(), entry.getValue());
                log.debug("Loaded .env property: {}={}", entry.getKey(), mask(entry.getKey(), entry.getValue()));
            });

            if (dotenvProperties.isEmpty()) {
                log.info("No .env entries found — relying on system environment variables");
                return;
            }

            // addFirst: .env wins over application.properties. That is what
            // makes a local override work without editing a committed file.
            propertySources.addFirst(new MapPropertySource("dotenv", dotenvProperties));
            log.info(".env loaded — {} propert{} available", dotenvProperties.size(),
                    dotenvProperties.size() == 1 ? "y" : "ies");

        } catch (Exception e) {
            // Not fatal: the same values can come from real environment
            // variables, which is how this runs in any deployed setting.
            log.warn("Could not read .env ({}) — using system environment variables", e.getMessage());
        }
    }

    /** Redact anything whose key suggests it is a credential. */
    private String mask(String key, String value) {
        if (value == null || value.isEmpty()) return "";

        String upper = key.toUpperCase();
        for (String marker : SECRET_MARKERS) {
            if (upper.contains(marker)) {
                return "***redacted***";
            }
        }
        return value;
    }
}
