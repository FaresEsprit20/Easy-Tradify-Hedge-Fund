package com.trading.easytradify.auth.repository;

import com.trading.easytradify.auth.entities.UnifiedToken;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;

import java.util.Optional;

@org.springframework.stereotype.Repository
public interface PasswordResetTokenRepository extends Repository<UnifiedToken, Long> {

    @Query("SELECT t FROM UnifiedToken t WHERE t.token = :token AND t.tokenType = 'PASSWORD_RESET'")
    Optional<UnifiedToken> findByToken(String token);

    @Modifying
    @Query("DELETE FROM UnifiedToken t WHERE t.userEmail = :email AND t.tokenType = 'PASSWORD_RESET'")
    void deleteByUserEmail(String email);

    @Query("SELECT t FROM UnifiedToken t WHERE t.userEmail = :userEmail AND t.tokenType = 'PASSWORD_RESET' ORDER BY t.creationDate DESC")
    Optional<UnifiedToken> findTopByUserEmailOrderByCreationDateDesc(String userEmail);
} 