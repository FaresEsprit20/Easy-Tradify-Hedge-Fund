package com.trading.easytradify.auth.dto.user;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class UserPaymentInfoDto {
    private Integer id;
    private String email;
    private String firstName;
    private String lastName;
    private String numTel;
}