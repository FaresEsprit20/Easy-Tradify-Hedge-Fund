package com.trading.easytradify.auth.dto.user;

import com.trading.easytradify.auth.dto.address.AddressDto;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import lombok.extern.slf4j.Slf4j;

import java.time.LocalDate;

@AllArgsConstructor
@NoArgsConstructor
@Data
@Builder
@Slf4j
public class RegisterRequest {

    private String firstName;
    private String lastName;
    private String email;
    private String username;
    private String numTel;
    private LocalDate birthDate;
    private String password;
    private String photo;
    private AddressDto address;

}
