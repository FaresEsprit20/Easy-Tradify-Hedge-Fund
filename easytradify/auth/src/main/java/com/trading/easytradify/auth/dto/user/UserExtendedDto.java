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
public class UserExtendedDto {

    private Integer id;
    private String firstName;
    private String lastName;
    private String email;
    private String username;
    private String numTel;
    private LocalDate birthDate;
    @JsonIgnore
    private String password;
    private String photo;
    private boolean twoFactorEnabled;
    private List<RolesDto> roles;
    private AddressDto address;

    public static UserExtendedDto fromEntity(User user) {
        if (user == null) {
            log.warn("Trying to convert null User entity to UserDto");
            return new UserExtendedDto(); // returns all defaults: "", null, empty list
        }

        return UserExtendedDto.builder()
                .id(user.getId())
                .firstName(user.getFirstName() != null ? user.getFirstName() : "")
                .lastName(user.getLastName() != null ? user.getLastName() : "")
                .email(user.getEmail() != null ? user.getEmail() : "")
                .username(user.getLoginName() != null ? user.getLoginName() : "")
                .twoFactorEnabled(Boolean.TRUE.equals(user.getTwoFactorEnabled()))
                .numTel(user.getNumTel() != null ? user.getNumTel() : "")
                // Left null when unset, rather than substituted.
                //
                // This line used to read LocalDate.from(... : Instant.EPOCH),
                // which throws for every user without a birth date: an Instant
                // is a point on the timeline with no date until a time zone is
                // applied, so LocalDate.from cannot read one. The guard meant
                // to handle null was the thing that failed on it, and the whole
                // response 500'd - which is what any account created through
                // Google sign-in hits, since those carry no birth date.
                //
                // A date nobody supplied is unknown; 1970-01-01 would be a
                // value the profile screen then shows as fact.
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


    public static UserDto toUserDTO(UserExtendedDto userExtendedDto) {
        if (userExtendedDto == null) {
            log.warn("Trying to convert null User entity to UserDto");
            return new UserDto(); // returns all defaults: "", null, empty list
        }

        return UserDto.builder()
                .firstName(userExtendedDto.getFirstName() != null ? userExtendedDto.getFirstName() : "")
                .lastName(userExtendedDto.getLastName() != null ? userExtendedDto.getLastName() : "")
                .email(userExtendedDto.getEmail() != null ? userExtendedDto.getEmail() : "")
                .birthDate(userExtendedDto.getBirthDate())
                .password(userExtendedDto.getPassword() != null ? userExtendedDto.getPassword() : "")
                .photo(userExtendedDto.getPhoto() != null ? userExtendedDto.getPhoto() : "")
                .roles(userExtendedDto.getRoles() != null
                        ? userExtendedDto.getRoles().stream()
                        .map(role -> role != null ? role : new RolesDto())
                        .collect(Collectors.toList())
                        : Collections.emptyList())
                .address(userExtendedDto.getAddress() != null ? userExtendedDto.getAddress() : new AddressDto())
                .build();
    }

    public static List<UserExtendedDto> toListDto(List<User> userList) {
        List<UserExtendedDto> userDtoList = new ArrayList<>();
        userList.forEach(user -> {
            userDtoList.add(fromEntity(user));
        });
        return userDtoList;
    }

    public static User toEntity(UserExtendedDto userDto) {
        if (userDto == null) {
            log.warn("Trying to convert null UserDto to User entity");
            return new User(); // returns empty User
        }

        User user = new User();
        user.setId(userDto.getId());
        user.setFirstName(userDto.getFirstName() != null ? userDto.getFirstName() : "");
        user.setLastName(userDto.getLastName() != null ? userDto.getLastName() : "");
        user.setEmail(userDto.getEmail() != null ? userDto.getEmail() : "");
        user.setBirthDate(userDto.getBirthDate() != null ? userDto.getBirthDate() : null);
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

    public static List<User> toListEntity(List<UserExtendedDto> userDtoList) {
        List<User> userList = new ArrayList<>();
        userDtoList.forEach(userDto -> {
            userList.add(toEntity(userDto));
        });
        return userList;
    }


}
