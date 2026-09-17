package com.trading.easytradify.common.entities.embedded;

import jakarta.persistence.Embeddable;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * A postal address, embedded into the owning row rather than given a table.
 *
 * <p>
 * Embedded because an address here has no identity of its own — it is never
 * shared between users and never queried independently, so a join table would
 * add a foreign key and a fetch for no benefit. The columns land directly on
 * {@code users}.
 * </p>
 */
@Data
@Builder
@AllArgsConstructor
@NoArgsConstructor
@Embeddable
public class Address {

    private String address1;
    private String address2;
    private String city;
    private String zipCode;
    private String country;
}
