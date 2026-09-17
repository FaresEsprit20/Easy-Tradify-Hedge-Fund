package com.trading.easytradify.auth.controllers.accounts;

import com.trading.easytradify.auth.dto.address.AddressDto;
import com.trading.easytradify.auth.dto.roles.RolesDto;
import com.trading.easytradify.auth.dto.user.RegisterRequest;
import com.trading.easytradify.auth.dto.user.UserDto;
import com.trading.easytradify.auth.entities.enums.UserRole;
import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.InvalidEntityException;
import com.trading.easytradify.auth.services.users.UserService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.RestController;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

@RestController
public class AccountManagementController implements AccountManagementApi {

    private final UserService userService;

    @Autowired
    public AccountManagementController(UserService userService) {
        this.userService = userService;
    }

    @Override
    public UserDto saveAdmin(RegisterRequest registerRequest) {
        List<String> errors = new ArrayList<>();
        if (registerRequest == null) {
            errors.add("User is required, NULL value found");
            throw new InvalidEntityException("User is required, NULL value found", ErrorCodes.USER_NOT_VALID,
                    errors);
        }
        RolesDto adminRole = new RolesDto();
        adminRole.setRoleName(UserRole.ADMIN);
        RolesDto managerRole = new RolesDto();
        managerRole.setRoleName(UserRole.USER);
        List<RolesDto> roles = new ArrayList<>(Arrays.asList(adminRole, managerRole));

        UserDto userDto = UserDto.builder()
                .firstName(registerRequest.getFirstName())
				.lastName(registerRequest.getLastName())
				.email(registerRequest.getEmail())
                .username(registerRequest.getUsername())
                .numTel(registerRequest.getNumTel())
				.password(registerRequest.getPassword())
				.address(AddressDto.builder()
                        .address1(registerRequest.getAddress().getAddress1())
                        .address2(registerRequest.getAddress().getAddress2())
                        .city(registerRequest.getAddress().getCity())
                        .country(registerRequest.getAddress().getCountry())
                        .zipCode(registerRequest.getAddress().getZipCode()).build())
				.birthDate(registerRequest.getBirthDate())
				.photo(registerRequest.getPhoto())
                .roles(roles)
                .build();
        return userService.save(userDto);
    }

    @Override
    public UserDto saveUser(RegisterRequest registerRequest) {
        List<String> errors = new ArrayList<>();
        if (registerRequest == null) {
            errors.add("User is required, NULL value found");
            throw new InvalidEntityException("User is required, NULL value found", ErrorCodes.USER_NOT_VALID,
                    errors);
            }
        RolesDto managerRole = new RolesDto();
        managerRole.setRoleName(UserRole.USER);
        List<RolesDto> roles = new ArrayList<>(List.of(managerRole));


        UserDto userDto = UserDto.builder()
                .firstName(registerRequest.getFirstName())
                .lastName(registerRequest.getLastName())
                .email(registerRequest.getEmail())
                .username(registerRequest.getUsername())
                .password(registerRequest.getPassword())
                .numTel(registerRequest.getNumTel())
                .address(AddressDto.builder()
                        .address1(registerRequest.getAddress().getAddress1())
                        .address2(registerRequest.getAddress().getAddress2())
                        .city(registerRequest.getAddress().getCity())
                        .country(registerRequest.getAddress().getCountry())
                        .zipCode(registerRequest.getAddress().getZipCode()).build())
                .birthDate(registerRequest.getBirthDate())
                .photo(registerRequest.getPhoto())
                .roles(roles)
                .build();

        return userService.save(userDto);
    }

    @Override
    public UserDto toggleLockAccount(Integer accountId) {
        return userService.toggleLock(accountId);
    }

    @Override
    public void delete(Integer id) {
        userService.delete(id);
    }


}
