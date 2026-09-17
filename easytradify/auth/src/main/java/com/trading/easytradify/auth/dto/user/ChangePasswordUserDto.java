package com.trading.easytradify.auth.dto.user;

import lombok.AllArgsConstructor;
import lombok.Data;

@Data
@AllArgsConstructor
public class ChangePasswordUserDto {

    private Integer id;
    private String password;
    private String confirmPassword;

}
