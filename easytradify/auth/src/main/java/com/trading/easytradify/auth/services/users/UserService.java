package com.trading.easytradify.auth.services.users;

import com.trading.easytradify.common.dto.auth.ChangePasswordUserRequestDto;
import com.trading.easytradify.auth.dto.user.ChangePasswordUserDto;
import com.trading.easytradify.auth.dto.user.UserDto;
import com.trading.easytradify.auth.dto.user.UserExtendedDto;
import com.trading.easytradify.auth.dto.user.UserUpdateDto;
import com.trading.easytradify.auth.entities.User;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.security.core.Authentication;


public interface UserService {

    UserDto save(UserDto userDto);

    boolean existsByEmail(String email);

    UserDto update(UserUpdateDto userDto, Authentication authentication);

    UserExtendedDto findById(Integer userId);

    Page<UserExtendedDto> findAll(Specification<User> specification, Pageable pageable);

    void delete(Integer userId);

    UserExtendedDto findByEmail(String email);

    UserExtendedDto changePassword(ChangePasswordUserRequestDto dto);

    UserExtendedDto changeProfilePassword(ChangePasswordUserDto dto);


    UserDto toggleLock(Integer userId);


    Integer findUserIdByEmail(String userEmail);
}