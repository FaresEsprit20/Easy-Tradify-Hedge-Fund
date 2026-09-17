package com.trading.easytradify.auth.dto.recpatcha;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@NoArgsConstructor
@AllArgsConstructor
@Data
public class RecaptchaV3Response {

    private boolean success;

    @JsonProperty("challenge_ts")
    private String challengeTimestamp;

    private String hostname;

    @JsonProperty("error-codes")
    private List<String> errorCodes;

    // v3 specific fields
    private Float score;
    private String action;

    @Override
    public String toString() {
        return "RecaptchaV3Response{" +
                "success=" + success +
                ", score=" + score +
                ", action='" + action + '\'' +
                ", hostname='" + hostname + '\'' +
                ", challengeTimestamp='" + challengeTimestamp + '\'' +
                ", errorCodes=" + errorCodes +
                '}';
    }


}