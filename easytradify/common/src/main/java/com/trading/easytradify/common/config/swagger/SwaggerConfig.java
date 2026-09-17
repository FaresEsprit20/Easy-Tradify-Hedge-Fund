package com.trading.easytradify.common.config.swagger;

import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class SwaggerConfig {

    @Bean
    public OpenAPI customOpenAPI() {
        return new OpenAPI()
                .info(new Info()
                        .title("Easy Tradyfy Hedge Fund 2.0 API ")
                        .version("1.0")
                        .description(" The new Release API 2.0 for financial market tools, and the related " +
                                "Hedge Fund 2.o Financial Modeling and Trading Platform."));
    }


}
