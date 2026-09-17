package com.trading.easytradify.auth.dto.user;

import com.trading.easytradify.auth.dto.address.AddressDto;
import com.trading.easytradify.auth.entities.User;
import com.trading.easytradify.common.entities.embedded.Address;
import lombok.*;
import lombok.extern.slf4j.Slf4j;
import java.util.ArrayList;
import java.util.List;


@AllArgsConstructor
@NoArgsConstructor
@EqualsAndHashCode
@Data
@Builder
@Slf4j
public class UserUpdateDto {

    private String email;
    private String firstName;
    private String lastName;
    private String numTel;
    private String photo;
    private AddressDto address;

    public static UserUpdateDto fromEntity(User user) {
        if (user == null) {
            log.warn("Trying to convert null User entity to UserDto");
            return new UserUpdateDto(); // returns all defaults: "", null, empty list
        }

        return UserUpdateDto.builder()
                .email(user.getEmail())
                .firstName(user.getFirstName())
                .lastName(user.getLastName())
                .numTel(user.getNumTel())
                .photo(user.getPhoto() != null ? user.getPhoto() : "")
                .address(user.getAddress() != null ? AddressDto.fromEntity(user.getAddress()) : new AddressDto())
                .build();
    }


    public static UserUpdateDto toUserDTO(UserExtendedDto userExtendedDto) {
        if (userExtendedDto == null) {
            log.warn("Trying to convert null User entity to UserDto");
            return new UserUpdateDto(); // returns all defaults: "", null, empty list
        }

        return UserUpdateDto.builder()
                .email(userExtendedDto.getEmail())
                .numTel(userExtendedDto.getNumTel())
                .photo(userExtendedDto.getPhoto() != null ? userExtendedDto.getPhoto() : "")
                .address(userExtendedDto.getAddress() != null ? userExtendedDto.getAddress() : new AddressDto())
                .build();
    }

    public static List<UserUpdateDto> toListDto(List<User> userList) {
        List<UserUpdateDto> userDtoList = new ArrayList<>();
        userList.forEach(user -> {
            userDtoList.add(fromEntity(user));
        });
        return userDtoList;
    }

    public static User toEntity(UserUpdateDto userDto) {
        if (userDto == null) {
            log.warn("Trying to convert null UserDto to User entity");
            return new User(); // returns empty User
        }

        User user = new User();
        user.setEmail(userDto.getEmail());
        user.setNumTel(userDto.getNumTel());
        user.setPhoto(userDto.getPhoto() != null ? userDto.getPhoto() : "");
        user.setAddress(userDto.getAddress() != null ? AddressDto.toEntity(userDto.getAddress()) : new Address());
        return user;
    }

    public static List<User> toListEntity(List<UserUpdateDto> userDtoList) {
        List<User> userList = new ArrayList<>();
        userDtoList.forEach(userDto -> {
            userList.add(toEntity(userDto));
        });
        return userList;
    }


}
