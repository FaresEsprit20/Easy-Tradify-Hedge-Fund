package com.trading.easytradify.auth.dto.address;

import com.trading.easytradify.common.entities.embedded.Address;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@AllArgsConstructor
@NoArgsConstructor
public class AddressDto {

    private String address1;
    private String address2;
    private String city;
    private String zipCode;
    private String country;

    // Static conversion methods
    public static AddressDto fromEntity(Address address) {
        if (address == null) {
            return null;
        }
        return new AddressDto(
                address.getAddress1() != null ? address.getAddress1() : "", // Default to empty string if null
                address.getAddress2() != null ? address.getAddress2() : "",
                address.getCity() != null ? address.getCity() : "",
                address.getZipCode() != null ? address.getZipCode() : "",
                address.getCountry() != null ? address.getCountry() : ""
        );
    }

    public static Address toEntity(AddressDto addressDto) {
        if (addressDto == null) {
            return null;
        }
        return new Address(
                addressDto.getAddress1(),
                addressDto.getAddress2(),
                addressDto.getCity(),
                addressDto.getZipCode(),
                addressDto.getCountry()
        );
    }


}
