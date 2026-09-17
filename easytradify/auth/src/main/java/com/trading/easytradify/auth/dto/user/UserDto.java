package com.trading.easytradify.auth.dto.user;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.trading.easytradify.auth.dto.address.AddressDto;
import com.trading.easytradify.auth.dto.roles.RolesDto;
import com.trading.easytradify.auth.entities.User;
import com.trading.easytradify.common.entities.embedded.Address;
import lombok.*;
import lombok.extern.slf4j.Slf4j;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.stream.Collectors;

@AllArgsConstructor
@NoArgsConstructor
@EqualsAndHashCode
@Data
@Builder
@Slf4j
public class UserDto {

    private String firstName;
    private String lastName;
    private String email;
    private String username;
    private String numTel;
    private LocalDate birthDate;
    @JsonIgnore
    private String password;
    private String photo;
    private List<RolesDto> roles;
    private AddressDto address;

    public static UserDto fromEntity(User user) {
        if (user == null) {
            log.warn("Trying to convert null User entity to UserDto");
            return new UserDto(); // returns all defaults: "", null, empty list
        }

        return UserDto.builder()
                .firstName(user.getFirstName() != null ? user.getFirstName() : "")
                .lastName(user.getLastName() != null ? user.getLastName() : "")
                .email(user.getEmail() != null ? user.getEmail() : "")
                .username(user.getLoginName() != null ? user.getLoginName() : "")
                .numTel(user.getNumTel()!= null ? user.getNumTel() : "")
                .birthDate(user.getBirthDate())
                .password(user.getPassword() != null ? user.getPassword() : "")
                .photo(user.getPhoto() != null ? user.getPhoto() : "")
                .roles(user.getRoles() != null
                        ? user.getRoles().stream()
                        .map(role -> role != null ? RolesDto.fromEntity(role) : new RolesDto())
                        .collect(Collectors.toList())
                        : Collections.emptyList())
                .address(user.getAddress() != null ? AddressDto.fromEntity(user.getAddress()) : new AddressDto())
                .build();
    }

    public static List<UserDto> toListDto(List<User> userList) {
        List<UserDto> userDtoList = new ArrayList<>();
        userList.forEach(user -> {
            userDtoList.add(fromEntity(user));
        });
        return userDtoList;
    }

    public static User toEntity(UserDto userDto) {
        if (userDto == null) {
            log.warn("Trying to convert null UserDto to User entity");
            return new User(); // returns empty User
        }

        User user = new User();
        user.setFirstName(userDto.getFirstName() != null ? userDto.getFirstName() : "");
        user.setLastName(userDto.getLastName() != null ? userDto.getLastName() : "");
        user.setEmail(userDto.getEmail() != null ? userDto.getEmail() : "");
        // Left null (not "") when absent: loginName is unique, and unlike ""
        // colliding across every username-less user, Postgres treats NULL
        // as distinct from every other NULL under a unique constraint.
        user.setLoginName(userDto.getUsername() != null && !userDto.getUsername().isBlank() ? userDto.getUsername().trim() : null);
        user.setNumTel(userDto.getNumTel() != null ? userDto.getNumTel() : "");
        user.setBirthDate(userDto.getBirthDate());
        user.setPassword(userDto.getPassword() != null ? userDto.getPassword() : "");
        user.setPhoto(userDto.getPhoto() != null ? userDto.getPhoto() : "");
        user.setAddress(userDto.getAddress() != null ? AddressDto.toEntity(userDto.getAddress()) : new Address());
        user.setRoles(userDto.getRoles() != null
                ? userDto.getRoles().stream()
                .map(roleDto -> roleDto != null ? RolesDto.toEntity(roleDto) : null)
                .collect(Collectors.toList())
                : Collections.emptyList());
        return user;
    }

    public static List<User> toListEntity(List<UserDto> userDtoList) {
       List<User> userList = new ArrayList<>();
         userDtoList.forEach(userDto -> {
              userList.add(toEntity(userDto));
         });
      return userList;
    }


}
