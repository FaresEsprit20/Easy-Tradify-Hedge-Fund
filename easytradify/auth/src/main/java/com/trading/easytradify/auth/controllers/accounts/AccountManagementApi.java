package com.trading.easytradify.auth.controllers.accounts;

import com.trading.easytradify.auth.dto.user.RegisterRequest;
import com.trading.easytradify.auth.dto.user.UserDto;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.*;

import static com.trading.easytradify.common.utils.constants.Constants.ACCOUNTS_ENDPOINT;
import static com.trading.easytradify.common.utils.constants.Constants.USER_ENDPOINT;


@Tag(name = "Account Management", description = "API for account management")
public interface AccountManagementApi {


        @PostMapping(ACCOUNTS_ENDPOINT + "/admin/create")
        @Operation(summary = "Create or update an admin user",
                description = "Creates a new an admin user or updates an existing one")
        @ApiResponses(value = {
                @ApiResponse(responseCode = "200", description = "Admin User successfully saved/updated"),
                @ApiResponse(responseCode = "400", description = "Invalid Admin data provided")
        })
        UserDto saveAdmin(@RequestBody RegisterRequest dto);

        @PostMapping(ACCOUNTS_ENDPOINT + "/user/create")
        @Operation(summary = "Create or update a user",
                description = "Creates a new a user or updates an existing one")
        @ApiResponses(value = {
                @ApiResponse(responseCode = "200", description = "User successfully saved/updated"),
                @ApiResponse(responseCode = "400", description = "Invalid User data provided")
        })
        UserDto saveUser(@RequestBody RegisterRequest dto);

        @Operation(summary = "Lock/Unlock user",
                description = "Locks or Unlocks a Manager User Account by an ADMIN User")
        @ApiResponses(value = {
                @ApiResponse(responseCode = "200", description = "Lock successful"),
                @ApiResponse(responseCode = "401", description = "Unauthorized - Invalid operation"),
                @ApiResponse(responseCode = "400", description = "Bad request - Invalid input")
        })
        @PutMapping(ACCOUNTS_ENDPOINT + "/lock/toggle/{accountId}")
        UserDto toggleLockAccount(@PathVariable Integer accountId);


        @DeleteMapping(USER_ENDPOINT + "/delete/{userId}")
        @Operation(summary = "Delete user",
                description = "Permanently deletes a user account")
        @ApiResponses(value = {
                @ApiResponse(responseCode = "200", description = "User successfully deleted"),
                @ApiResponse(responseCode = "404", description = "User not found with the provided ID")
        })
        void delete(
                @Parameter(description = "ID of the user to be deleted")
                @PathVariable("userId") Integer id);



}

