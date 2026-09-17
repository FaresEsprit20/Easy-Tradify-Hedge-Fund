package com.trading.easytradify.auth.services.users;

import com.trading.easytradify.common.dto.auth.ChangePasswordUserRequestDto;
import com.trading.easytradify.auth.dto.user.ChangePasswordUserDto;
import com.trading.easytradify.auth.dto.user.UserDto;
import com.trading.easytradify.auth.dto.user.UserExtendedDto;
import com.trading.easytradify.auth.dto.user.UserUpdateDto;
import com.trading.easytradify.auth.entities.Roles;
import com.trading.easytradify.auth.entities.User;
import com.trading.easytradify.common.entities.embedded.Address;
import com.trading.easytradify.auth.entities.enums.TokenType;
import com.trading.easytradify.common.exception.EntityNotFoundException;
import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.InvalidEntityException;
import com.trading.easytradify.common.exception.InvalidOperationException;
import com.trading.easytradify.auth.repository.RolesRepository;
import com.trading.easytradify.auth.repository.UnifiedTokenRepository;
import com.trading.easytradify.auth.repository.UserRepository;
import com.trading.easytradify.auth.validators.email.EmailValidator;
import com.trading.easytradify.auth.validators.password.PasswordValidator;
import com.trading.easytradify.auth.validators.users.UserUpdateValidator;
import com.trading.easytradify.auth.validators.users.UserValidator;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.security.core.Authentication;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Optional;

@Slf4j
@Service
@Transactional
public class UserServiceImpl implements UserService {

    private final UserRepository userRepository;
    private final RolesRepository rolesRepository;
    private final UnifiedTokenRepository unifiedTokenRepository;

    @Autowired
    private PasswordEncoder passwordEncoder;

    @Autowired
    public UserServiceImpl(UserRepository userRepository, RolesRepository rolesRepository, UnifiedTokenRepository unifiedTokenRepository) {
        this.userRepository = userRepository;
        this.rolesRepository = rolesRepository;
        this.unifiedTokenRepository = unifiedTokenRepository;
    }

    @Override
    @Transactional
    public UserDto save(UserDto dto) {
        List<String> errors = UserValidator.validate(dto);
        if (!errors.isEmpty()) {
            log.error("User is not valid {}", dto);
            log.warn("Errors : {}", errors);
            throw new InvalidEntityException("The user is not valid", ErrorCodes.USER_NOT_VALID, errors);
        }

        // Check if email already exists
        if (userRepository.existsByEmail(dto.getEmail())) {
            throw new InvalidEntityException("Another user with the same email already exists", ErrorCodes.USER_ALREADY_EXISTS,
                    Collections.singletonList("Another user with the same email already exists in the DB"));
        }

        // Check if username already exists (optional field, so only checked when provided)
        if (dto.getUsername() != null && !dto.getUsername().trim().isEmpty()
                && userRepository.existsByLoginName(dto.getUsername().trim())) {
            throw new InvalidEntityException("Another user with the same username already exists", ErrorCodes.USER_ALREADY_EXISTS,
                    Collections.singletonList("Another user with the same username already exists in the DB"));
        }

        // Check if phone number already exists - JUST LIKE EMAIL CHECK
        if (dto.getNumTel() != null && !dto.getNumTel().trim().isEmpty()) {
            Optional<User> existingUserByPhone = userRepository.findUserByNumTel(dto.getNumTel().trim());
            if (existingUserByPhone.isPresent()) {
                throw new InvalidOperationException(
                        "Phone number " + dto.getNumTel() + " is already registered to another user",
                        ErrorCodes.USER_ALREADY_EXISTS,
                        Collections.singletonList("Phone number already exists")
                );
            }
        }

        dto.setPassword(passwordEncoder.encode(dto.getPassword()));

        User userEntity = UserDto.toEntity(dto);

        // Handle roles - fetch existing roles from database
        if (userEntity.getRoles() != null && !userEntity.getRoles().isEmpty()) {
            List<Roles> managedRoles = new ArrayList<>();
            for (Roles role : userEntity.getRoles()) {
                Optional<Roles> existingRole = rolesRepository.findByRoleName(role.getRoleName());
                if (existingRole.isPresent()) {
                    managedRoles.add(existingRole.get());
                } else {
                    log.warn("Role {} not found in database, creating new one", role.getRoleName());
                    Roles newRole = new Roles();
                    newRole.setRoleName(role.getRoleName());
                    managedRoles.add(rolesRepository.save(newRole));
                }
            }
            userEntity.setRoles(managedRoles);
        }

        User savedUser = userRepository.save(userEntity);
        log.info("User saved successfully with ID: {} and roles: {}, phone number: {}",
                savedUser.getId(),
                savedUser.getRoles().stream().map(r -> r.getRoleName().name()).toList(),
                savedUser.getNumTel());

        return UserDto.fromEntity(savedUser);
    }

    @Override
    public boolean existsByEmail(String email) {
        return userRepository.existsByEmail(email);
    }

    @Override
    @Transactional
    public UserDto update(UserUpdateDto userDto, Authentication authentication) {
        List<String> errors = UserUpdateValidator.validate(userDto);
        if (!errors.isEmpty()) {
            log.error("User is not valid {}", userDto);
            log.warn("Errors : {}", errors);
            throw new InvalidEntityException("The user is not valid", ErrorCodes.USER_NOT_VALID, errors);
        }

        Optional<User> userEntity = userRepository.findUserByEmail(authentication.getName());
        if (userEntity.isEmpty()) {
            errors.add("User with Email = " + authentication.getName() + " is not found");
            throw new EntityNotFoundException("User with Email = " + authentication.getName() + " is not found",
                    ErrorCodes.USER_NOT_FOUND, errors);
        }
        if (!userDto.getEmail().equals(userEntity.get().getEmail())) {
            log.warn("Mismatch between authenticated user and provided email");
            errors.add("Authenticated user does not match the email in request body");
            throw new InvalidOperationException("Impossible to proceed with update",
                    ErrorCodes.USER_NOT_VALID, errors);
        }

        // Check if phone number is being changed and validate uniqueness
        if (userDto.getNumTel() != null && !userDto.getNumTel().equals(userEntity.get().getNumTel())) {
            Optional<User> existingUserByPhone = userRepository.findUserByNumTel(userDto.getNumTel().trim());
            if (existingUserByPhone.isPresent() && !existingUserByPhone.get().getId().equals(userEntity.get().getId())) {
                throw new InvalidOperationException(
                        "Phone number " + userDto.getNumTel() + " is already registered to another user",
                        ErrorCodes.USER_ALREADY_EXISTS,
                        Collections.singletonList("Phone number already exists")
                );
            }
            userEntity.get().setNumTel(userDto.getNumTel());
        }

        userEntity.get().setFirstName(userDto.getFirstName());
        userEntity.get().setLastName(userDto.getLastName());

        Address address = userEntity.get().getAddress();
        address.setAddress1(userDto.getAddress().getAddress1());
        address.setAddress2(userDto.getAddress().getAddress2());
        address.setCity(userDto.getAddress().getCity());
        address.setCountry(userDto.getAddress().getCountry());
        address.setZipCode(userDto.getAddress().getZipCode());
        userEntity.get().setAddress(address);
        userEntity.get().setPhoto(userDto.getPhoto());

        return UserDto.fromEntity(userRepository.save(userEntity.get()));
    }

    @Transactional
    protected boolean userAlreadyExists(String email) {
        Optional<User> user = userRepository.findUserByEmail(email);
        return user.isPresent();
    }

    @Override
    @Transactional
    public UserExtendedDto findById(Integer userId) {
        List<String> errors = new ArrayList<>();
        if (userId == null) {
            log.error("User ID is null");
            errors.add("User ID is null");
            throw new InvalidEntityException("The user ID is not valid", ErrorCodes.USER_NOT_VALID, errors);
        }
        errors.add("No user with the ID = " + userId + " has been found in the DB");
        return userRepository.findById(userId)
                .map(UserExtendedDto::fromEntity)
                .orElseThrow(() -> new EntityNotFoundException(
                        "No user with the ID = " + userId + " has been found in the DB",
                        ErrorCodes.USER_NOT_FOUND, errors)
                );
    }

    @Override
    @Transactional
    public Page<UserExtendedDto> findAll(Specification<User> specification, Pageable pageable) {
        return userRepository.findAll(specification, pageable)
                .map(UserExtendedDto::fromEntity);
    }

    @Override
    @Transactional
    public UserExtendedDto findByEmail(String email) {
        List<String> errors = EmailValidator.validate(email);
        if (!errors.isEmpty()) {
            log.error("User Email is Not Valid");
            errors.add("User Email is Not Valid");
            throw new InvalidEntityException("User Email is Not Valid",
                    ErrorCodes.USER_NOT_VALID, errors);
        }
        errors.add("No user with the email = " + email + " has been found in the DB");
        return userRepository.findUserByEmail(email)
                .map(UserExtendedDto::fromEntity)
                .orElseThrow(() -> new EntityNotFoundException(
                        "No user with the email = " + email + " has been found in the DB",
                        ErrorCodes.USER_NOT_FOUND, errors)
                );
    }

    @Override
    @Transactional
    public UserExtendedDto changePassword(ChangePasswordUserRequestDto dto) {
        validatePassword(dto);
        List<String> errors = new ArrayList<>();
        Optional<User> utilisateurOptional = userRepository.findById(dto.getId());
        if (utilisateurOptional.isEmpty()) {
            errors.add("No user with the ID = " + dto.getId() + " has been found in the DB");
            log.warn("No User has been found with the ID " + dto.getId());
            throw new EntityNotFoundException("No User has been found with the ID " + dto.getId(),
                    ErrorCodes.USER_NOT_FOUND, errors);
        }

        User user = utilisateurOptional.get();
        user.setPassword(passwordEncoder.encode(dto.getPassword()));

        return UserExtendedDto.fromEntity(userRepository.save(user));
    }

    @Override
    public UserExtendedDto changeProfilePassword(ChangePasswordUserDto dto) {
        validatePassword(dto);
        List<String> errors = new ArrayList<>();
        Optional<User> utilisateurOptional = userRepository.findById(dto.getId());
        if (utilisateurOptional.isEmpty()) {
            errors.add("No user with the ID = " + dto.getId() + " has been found in the DB");
            log.warn("No User has been found with the ID " + dto.getId());
            throw new EntityNotFoundException("No User has been found with the ID " + dto.getId(),
                    ErrorCodes.USER_NOT_FOUND, errors);
        }

        User user = utilisateurOptional.get();
        user.setPassword(passwordEncoder.encode(dto.getPassword()));

        return UserExtendedDto.fromEntity(userRepository.save(user));
    }

    @Override
    @Transactional
    public UserDto toggleLock(Integer userId) {
        List<String> errors = new ArrayList<>();
        if (userId == null) {
            errors.add("User ID is null");
            log.error("User ID is null");
            throw new InvalidEntityException("The user ID is not valid", ErrorCodes.USER_NOT_VALID, errors);
        }

        User user = userRepository.findById(userId)
                .orElseThrow(() -> new EntityNotFoundException(
                        "No user with the ID = " + userId + " has been found in the DB",
                        ErrorCodes.USER_NOT_FOUND, List.of("No user with the ID = " + userId + " has been found in the DB"))
                );

        boolean isAdmin = user.getRoles().stream()
                .anyMatch(role -> role.getRoleName().name().equals("ADMIN"));

        if (isAdmin) {
            errors.add("Impossible to lock/unlock user with ID " + userId +
                    " who has role ADMIN — INVALID OPERATION");
            throw new InvalidOperationException(
                    "Impossible to lock/unlock user with ID " + userId +
                            " who has role ADMIN — INVALID OPERATION",
                    ErrorCodes.USER_ACCOUNT_LOCK_NOT_VALID, errors);
        }

        user.setLocked(!user.getLocked());
        return UserDto.fromEntity(userRepository.save(user));
    }

    @Override
    public Integer findUserIdByEmail(String userEmail) {
        List<String> errors = new ArrayList<>();
        errors.add("No user with the email = " + userEmail + " has been found in the DB");
        return userRepository.findUserIdByEmail(userEmail)
                .orElseThrow(() -> new EntityNotFoundException(
                        "User with Email " + userEmail + " has not been found",
                        ErrorCodes.USER_NOT_FOUND,
                        errors
                ));
    }

    @Transactional
    protected void validatePassword(ChangePasswordUserRequestDto dto) {
        List<String> errors = new ArrayList<>();
        if (dto == null) {
            log.warn("Impossible to modify the password with a null object");
            errors.add("Impossible to modify the password with a null object");
            throw new InvalidOperationException("No Information has been provided to proceed for changing the password",
                    ErrorCodes.USER_CHANGE_PASSWORD_OBJECT_NOT_VALID, errors);
        }
        if (dto.getId() == null) {
            log.warn("Impossible to modify the password with a NULL ID");
            errors.add("Impossible to modify the password with a NULL ID");
            throw new InvalidOperationException("ID user is null:: Impossible to modify the password ",
                    ErrorCodes.USER_CHANGE_PASSWORD_OBJECT_NOT_VALID, errors);
        }
        if (!StringUtils.hasLength(dto.getPassword()) || !StringUtils.hasLength(dto.getConfirmPassword())) {
            log.warn("Impossible to modify the password with a NULL password");
            errors.add("Impossible to modify the password with a NULL password");
            throw new InvalidOperationException("Null Password:: Impossible to modify the password",
                    ErrorCodes.USER_CHANGE_PASSWORD_OBJECT_NOT_VALID, errors);
        }
        if (!dto.getPassword().equals(dto.getConfirmPassword())) {
            log.warn("Impossible to modify the password when your password and confirm password are not the same ");
            errors.add("Impossible to modify the password: Passwords do not match");
            throw new InvalidOperationException("User Passwords mismatch:: Impossible to modify the password when your password and confirm password are not the same",
                    ErrorCodes.USER_CHANGE_PASSWORD_OBJECT_NOT_VALID, errors);
        }

        List<String> passwordErrors = PasswordValidator.validate(dto.getPassword());
        if (!passwordErrors.isEmpty()) {
            errors.addAll(passwordErrors);
            throw new InvalidOperationException("Password Validation Error: ",
                    ErrorCodes.USER_CHANGE_PASSWORD_OBJECT_NOT_VALID, errors);
        }
    }

    @Transactional
    protected void validatePassword(ChangePasswordUserDto dto) {
        List<String> errors = new ArrayList<>();
        if (dto == null) {
            log.warn("Impossible to modify the password with a null object");
            errors.add("Impossible to modify the password with a null object");
            throw new InvalidOperationException("No Information has been provided to proceed for changing the password",
                    ErrorCodes.USER_CHANGE_PASSWORD_OBJECT_NOT_VALID, errors);
        }
        if (dto.getId() == null) {
            log.warn("Impossible to modify the password with a NULL ID");
            errors.add("Impossible to modify the password with a NULL ID");
            throw new InvalidOperationException("ID user is null:: Impossible to modify the password ",
                    ErrorCodes.USER_CHANGE_PASSWORD_OBJECT_NOT_VALID, errors);
        }
        if (!StringUtils.hasLength(dto.getPassword()) || !StringUtils.hasLength(dto.getConfirmPassword())) {
            log.warn("Impossible to modify the password with a NULL password");
            errors.add("Impossible to modify the password with a NULL password");
            throw new InvalidOperationException("Null Password:: Impossible to modify the password",
                    ErrorCodes.USER_CHANGE_PASSWORD_OBJECT_NOT_VALID, errors);
        }
        if (!dto.getPassword().equals(dto.getConfirmPassword())) {
            log.warn("Impossible to modify the password when your password and confirm password are not the same ");
            errors.add("Impossible to modify the password: Passwords do not match");
            throw new InvalidOperationException("User Passwords mismatch:: Impossible to modify the password when your password and confirm password are not the same",
                    ErrorCodes.USER_CHANGE_PASSWORD_OBJECT_NOT_VALID, errors);
        }

        List<String> passwordErrors = PasswordValidator.validate(dto.getPassword());
        if (!passwordErrors.isEmpty()) {
            errors.addAll(passwordErrors);
            throw new InvalidOperationException("Password Validation Error: ",
                    ErrorCodes.USER_CHANGE_PASSWORD_OBJECT_NOT_VALID, errors);
        }
    }

    @Override
    @Transactional
    public void delete(Integer userId) {
        List<String> errors = new ArrayList<>();

        if (userId == null) {
            log.error("User ID is null");
            errors.add("User ID is null");
            throw new InvalidEntityException(
                    "The user ID is not valid",
                    ErrorCodes.USER_NOT_VALID,
                    errors
            );
        }

        errors.add("No user with the ID = " + userId + " has been found in the DB");
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new EntityNotFoundException(
                        "No user with the ID = " + userId + " has been found in the DB",
                        ErrorCodes.USER_NOT_FOUND,
                        errors
                ));

        boolean isAdmin = user.getRoles().stream()
                .anyMatch(role -> role.getRoleName().name().equals("ADMIN"));

        if (isAdmin) {
            String errorMessage = "Impossible to delete a user with ID " + userId +
                    " who has role ADMIN — INVALID OPERATION";
            log.error(errorMessage);
            errors.add(errorMessage);
            throw new InvalidOperationException(
                    errorMessage,
                    ErrorCodes.USER_NOT_VALID,
                    errors
            );
        }

        // Delete all JWT tokens for the user
        unifiedTokenRepository.deleteByUserEmailAndType(user.getEmail(), TokenType.JWT);
        rolesRepository.deleteAllRolesForUser(userId);
        userRepository.deleteByIdCustom(userId);
    }
}