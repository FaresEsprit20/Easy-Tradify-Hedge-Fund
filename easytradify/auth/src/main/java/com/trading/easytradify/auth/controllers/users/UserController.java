package com.trading.easytradify.auth.controllers.users;

import com.trading.easytradify.auth.config.security.logout.LogoutService;
import com.trading.easytradify.common.dto.auth.ChangePasswordUserRequestDto;
import com.trading.easytradify.auth.dto.user.ChangePasswordUserDto;
import com.trading.easytradify.auth.dto.user.UserDto;
import com.trading.easytradify.auth.dto.user.UserExtendedDto;
import com.trading.easytradify.auth.dto.user.UserUpdateDto;
import com.trading.easytradify.auth.entities.User;
import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.InvalidEntityException;
import com.trading.easytradify.common.exception.InvalidOperationException;
import com.trading.easytradify.auth.services.auth.AuthenticationService;
import com.trading.easytradify.auth.services.users.UserService;
import com.trading.easytradify.auth.specifications.users.UserSpecification;
import com.trading.easytradify.common.utils.pagination.PaginationAndFilteringDto;
import com.trading.easytradify.common.utils.pagination.PaginationUtil;
import com.trading.easytradify.common.utils.pagination.response.PagedResponse;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

@RestController
public class UserController implements UserApi {

    private final UserService userService;
    private final LogoutService logoutService;
    private final AuthenticationService authenticationService;

    @Autowired
    public UserController(UserService userService, LogoutService logoutService, AuthenticationService authenticationService) {
        this.userService = userService;
        this.logoutService = logoutService;
        this.authenticationService = authenticationService;
    }


    @Override
    public UserDto update(UserUpdateDto userDto, Authentication authentication) {
        return userService.update(userDto, authentication);
    }

    @Override
    public UserExtendedDto changePassword(ChangePasswordUserRequestDto dto) {
        return userService.changePassword(dto);
    }

    @Override
    public UserExtendedDto changeProfilePassword(ChangePasswordUserDto dto) {
        return userService.changeProfilePassword(dto);
    }


    @Override
    public UserExtendedDto findById(Integer id) {
        return userService.findById(id);
    }


    @Override
    public UserExtendedDto findByEmail(String email) {
        return userService.findByEmail(email);
    }


    @Override
    public PagedResponse<UserExtendedDto> findAll(@RequestBody PaginationAndFilteringDto paginationAndFilteringDto) {

        Pageable pageable = PaginationUtil.createPageRequest(paginationAndFilteringDto);
        Specification<User> specification = UserSpecification.withFilters(
                paginationAndFilteringDto.getFilters());

        Page<UserExtendedDto> page = userService.findAll(specification, pageable);
        return new PagedResponse<>(
                page.getContent(),
                page.getNumber() + 1,
                page.getSize(),
                page.getTotalElements(),
                page.getTotalPages()
        );
    }

    public void refreshToken(
            HttpServletRequest request,
            HttpServletResponse response
    ) throws IOException {
        authenticationService.refreshToken(request, response);
    }


    @Override
    public ResponseEntity<UserExtendedDto> getAuthenticatedUser(Authentication authentication) {
        List<String> errors = new ArrayList<>();
        if (authentication == null || !authentication.isAuthenticated()) {
            errors.add(" Invalid authentication ");
            throw new InvalidOperationException(" The user is not Authenticated ",
                    ErrorCodes.USER_NOT_AUTHENTICATED, errors);
        }

        String email = authentication.getName();
        UserExtendedDto user = userService.findByEmail(email);
        if (user == null) {
            errors.add(" Invalid user ");
            throw new InvalidEntityException(" User is not valid", ErrorCodes.USER_NOT_VALID, errors);
        }
        return ResponseEntity.ok(user);
    }

    @Override
    public ResponseEntity<?> logoutUser(HttpServletRequest request, HttpServletResponse response,
                                        Authentication authentication) {
        // Clean all previous cookies BEFORE logout
        deleteAllCookies(request, response);
        logoutService.logout(request,response, authentication);
        return ResponseEntity.ok("Logged out successfully");
    }

    private void deleteAllCookies(HttpServletRequest request, HttpServletResponse response) {
        if (request.getCookies() != null) {
            for (Cookie cookie : request.getCookies()) {
                ResponseCookie expiredCookie = ResponseCookie.from(cookie.getName(), "")
                        .path("/")
                        .maxAge(0)
                        .httpOnly(cookie.isHttpOnly())
                        .secure(cookie.getSecure())
                        .sameSite("Strict")
                        .build();
                response.addHeader(HttpHeaders.SET_COOKIE, expiredCookie.toString());
            }
        }
    }

}
