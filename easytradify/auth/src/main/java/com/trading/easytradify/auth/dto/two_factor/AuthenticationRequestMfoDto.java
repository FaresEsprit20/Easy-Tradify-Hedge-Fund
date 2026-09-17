package com.trading.easytradify.auth.dto.two_factor;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;


@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class AuthenticationRequestMfoDto {

    @NotBlank(message = "Email or username cannot be blank")
    private String login;

    @NotBlank(message = "Password cannot be blank")
    private String password;

    @JsonProperty("recaptchaToken")
    @NotBlank(message = "Recaptcha token is required")
    private String recaptchaToken;

    @JsonProperty("remember_me")
    private Boolean rememberMe;

    // Fields for 2FA (used when submitting 2FA code)
    @JsonProperty("twoFactorCode")
    private String twoFactorCode;

    @JsonProperty("twoFactorMethod")
    private String twoFactorMethod;

}
