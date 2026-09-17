package com.trading.easytradify.auth.specifications.users;

import com.trading.easytradify.auth.entities.User;
import jakarta.persistence.criteria.Predicate;
import org.springframework.data.jpa.domain.Specification;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Turns the generic {@code filters} map from a pagination request into a JPA
 * {@code Specification}.
 *
 * <h2>Why the field names are allow-listed</h2>
 * <p>
 * The map arrives from the client as arbitrary key/value pairs. Passing a key
 * straight to {@code root.get(key)} would let a caller filter on — and so probe
 * — any mapped field, {@code password} and {@code totpSecret} included: a
 * binary search over "does a user exist whose password hash starts with…" is a
 * slow but entirely workable extraction. An unknown key is therefore ignored
 * rather than applied, and the sensitive columns are simply not in the list.
 * </p>
 */
public final class UserSpecification {

    private UserSpecification() {
        // Static utility.
    }

    /** The only fields a client may filter on. */
    private static final List<String> TEXT_FIELDS = List.of(
            "email", "firstName", "lastName", "loginName", "numTel", "provider"
    );

    public static Specification<User> withFilters(Map<String, String> filters) {
        return (root, query, builder) -> {
            List<Predicate> predicates = new ArrayList<>();

            if (filters != null) {
                for (Map.Entry<String, String> entry : filters.entrySet()) {
                    String field = entry.getKey();
                    String value = entry.getValue();

                    if (field == null || value == null || value.isBlank()) continue;

                    if (TEXT_FIELDS.contains(field)) {
                        // Case-insensitive contains. The value is bound as a
                        // parameter by the Criteria API, so the wildcards here
                        // cannot escape into the SQL itself.
                        predicates.add(builder.like(
                                builder.lower(root.get(field).as(String.class)),
                                "%" + value.trim().toLowerCase() + "%"
                        ));
                    } else if ("locked".equals(field)) {
                        predicates.add(builder.equal(root.get("locked"), Boolean.parseBoolean(value)));
                    } else if ("twoFactorEnabled".equals(field)) {
                        predicates.add(builder.equal(root.get("twoFactorEnabled"), Boolean.parseBoolean(value)));
                    } else if ("role".equals(field)) {
                        // Join rather than a path expression: roles is a
                        // ManyToMany, and root.get("roles") alone cannot be
                        // compared to a scalar.
                        predicates.add(builder.equal(
                                builder.lower(root.join("roles").get("roleName").as(String.class)),
                                value.trim().toLowerCase()
                        ));
                        if (query != null) query.distinct(true);
                    }
                    // Anything else is deliberately dropped — see the class note.
                }
            }

            // No recognised filters means no restriction, which is what an
            // unfiltered listing should do.
            return predicates.isEmpty()
                    ? builder.conjunction()
                    : builder.and(predicates.toArray(new Predicate[0]));
        };
    }
}
