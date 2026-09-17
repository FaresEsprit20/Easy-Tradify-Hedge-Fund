package com.trading.easytradify.auth.repository;

import com.trading.easytradify.auth.entities.User;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.JpaSpecificationExecutor;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import java.util.Optional;

@Repository
@Transactional
public interface UserRepository extends JpaRepository<User, Integer>, JpaSpecificationExecutor<User> {

    // JPQL query
    @Query(value = "select u from User u where u.email = :email")
    Optional<User> findUserByEmail(@Param("email") String email);

    @Query("select u from User u where u.email = :login or u.loginName = :login")
    Optional<User> findUserByEmailOrUsername(@Param("login") String login);

    boolean existsByLoginName(String loginName);

    /**
     * Finds a user by phone number, whatever role they hold.
     *
     * <p>This used to join roles and filter on {@code 'CUSTOMER'} — a value
     * that is not in {@link com.trading.easytradify.auth.entities.enums.UserRole},
     * which is {@code {USER, ADMIN}}. Hibernate validates enum literals
     * against the column's permitted values, so the query threw before it
     * could run and every registration failed with a 500: the sign-up path
     * calls this to check for a duplicate phone number.
     *
     * <p>The role filter is gone rather than corrected to {@code USER},
     * because both callers are duplicate-phone checks and an administrator
     * holding that number is just as much a conflict.
     */
    @Query("select u from User u where u.numTel = :numTel")
    Optional<User> findUserByNumTel(@Param("numTel") String numTel);

    boolean existsByEmail(String email);

    @Query("SELECT u.id FROM User u WHERE u.email = :email")
    Optional<Integer> findUserIdByEmail(@Param("email") String email);

    @Modifying

    @Query("DELETE FROM User u WHERE u.id = :id")
    void deleteByIdCustom(@Param("id") Integer id);

    @Query("select case when count(u) > 0 then true else false end from User u join u.roles r where u.email = :email and r.roleName = 'USER'")
    boolean existsUserByEmail(@Param("email") String email);

    @Query("select case when count(u) > 0 then true else false end from User u join u.roles r where u.numTel = :numTel and r.roleName = 'USER'")
    boolean existsUserByNumTel(@Param("numTel") String numTel);


    // NEW: For OAuth2 lookup
    Optional<User> findByProviderAndProviderId(String provider, String providerId);

    // Check if OAuth2 user exists
    boolean existsByProviderAndProviderId(String provider, String providerId);



}
