package com.trading.easytradify.auth.controllers.users;

import com.trading.easytradify.common.dto.auth.ChangePasswordUserRequestDto;
import com.trading.easytradify.auth.dto.user.ChangePasswordUserDto;
import com.trading.easytradify.auth.dto.user.UserDto;
import com.trading.easytradify.auth.dto.user.UserExtendedDto;
import com.trading.easytradify.auth.dto.user.UserUpdateDto;
import com.trading.easytradify.common.utils.pagination.PaginationAndFilteringDto;
import com.trading.easytradify.common.utils.pagination.response.PagedResponse;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import java.io.IOException;

import static com.trading.easytradify.common.utils.constants.Constants.USER_ENDPOINT;


@Tag(name = "Users", description = "API for user management")
public interface UserApi {

    @PutMapping(USER_ENDPOINT + "/update")
    @Operation(summary = "Update own user profile",
            description = "Allows an authenticated user to update their own profile information")
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "User successfully updated"),
            @ApiResponse(responseCode = "400", description = "Invalid user data provided"),
            @ApiResponse(responseCode = "403", description = "Access denied"),
            @ApiResponse(responseCode = "404", description = "User not found")
    })
    UserDto update(@RequestBody UserUpdateDto userDto, Authentication authentication);


    @PutMapping(USER_ENDPOINT + "/update/password")
    @Operation(summary = "Change user password",
            description = "Updates the password for an existing user")
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Password successfully changed"),
            @ApiResponse(responseCode = "400", description = "Invalid password data provided"),
            @ApiResponse(responseCode = "404", description = "User not found")
    })
    UserExtendedDto changePassword(@RequestBody ChangePasswordUserRequestDto dto);


    @PutMapping(USER_ENDPOINT + "/update/profile/password")
    @Operation(summary = "Change user profile password",
            description = "Updates the password for an existing user profile")
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Password successfully changed"),
            @ApiResponse(responseCode = "400", description = "Invalid password data provided"),
            @ApiResponse(responseCode = "404", description = "User not found")
    })
    UserExtendedDto changeProfilePassword(@RequestBody ChangePasswordUserDto dto);

    @GetMapping(USER_ENDPOINT + "/{userId}")
    @Operation(summary = "Find user by ID",
            description = "Retrieves user details by user ID")
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "User found"),
            @ApiResponse(responseCode = "404", description = "User not found with the provided ID")
    })
    UserExtendedDto findById(
            @Parameter(description = "ID of the user to be retrieved")
            @PathVariable("userId") Integer id);

    @GetMapping(USER_ENDPOINT + "/find/{email}")
    @Operation(summary = "Find user by email",
            description = "Retrieves user details by email address")
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "User found"),
            @ApiResponse(responseCode = "404", description = "User not found with the provided email")
    })
    UserExtendedDto findByEmail(
            @Parameter(description = "Email address of the user to be retrieved")
            @PathVariable("email") String email);


    @Operation(summary = "Get authenticated User")
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Authenticated User returned"),
            @ApiResponse(responseCode = "403", description = "No Authentication was Found")

    })
    @GetMapping(USER_ENDPOINT + "/auth-user")
    ResponseEntity<UserExtendedDto> getAuthenticatedUser(Authentication authentication);

    @PostMapping(USER_ENDPOINT + "/all")
    @Operation(summary = "Get all users",
            description = "Retrieves a list of all registered users")
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "List of users retrieved successfully")
    })
    PagedResponse<UserExtendedDto> findAll(@RequestBody PaginationAndFilteringDto paginationAndFilteringDto);


    @GetMapping(USER_ENDPOINT + "/refresh-token")
    @Operation(summary = "Refresh access token using refresh token",
            description = "Uses the provided refresh token to issue a new access token.")
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "Access token successfully refreshed"),
            @ApiResponse(responseCode = "400", description = "Invalid or expired refresh token"),
            @ApiResponse(responseCode = "401", description = "Authentication required")
    })
    void refreshToken(
            @Parameter(description = "Refresh token to use for obtaining a new access token")
            HttpServletRequest request,
            HttpServletResponse response
    ) throws IOException;

    @PostMapping(USER_ENDPOINT + "/logout")
    @Operation(summary = "Logout user",
            description = "Logs out the current user by clearing the authentication cookie")
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "User successfully logged out"),
            @ApiResponse(responseCode = "400", description = "Error during logout")
    })
    ResponseEntity<?> logoutUser(HttpServletRequest request, HttpServletResponse response,
                                 Authentication authentication);

}
