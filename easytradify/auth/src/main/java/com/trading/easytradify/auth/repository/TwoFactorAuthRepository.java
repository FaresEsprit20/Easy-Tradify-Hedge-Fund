package com.trading.easytradify.auth.repository;

import com.trading.easytradify.auth.entities.UnifiedToken;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

@org.springframework.stereotype.Repository
public interface TwoFactorAuthRepository extends Repository<UnifiedToken, Long> {

    @Query("SELECT t FROM UnifiedToken t WHERE t.token = :token AND t.userEmail = :userEmail AND t.tokenType = 'TWO_FACTOR'")
    Optional<UnifiedToken> findByTokenAndUserEmail(String token, String userEmail);

    @Modifying
    @Query("DELETE FROM UnifiedToken t WHERE t.userEmail = :email AND t.tokenType = 'TWO_FACTOR'")
    void deleteByUserEmail(String email);

    @Query("SELECT t FROM UnifiedToken t WHERE t.userEmail = :userEmail AND t.tokenType = 'TWO_FACTOR' ORDER BY t.creationDate DESC")
    Optional<UnifiedToken> findTopByUserEmailOrderByCreationDateDesc(String userEmail);

    @Query("SELECT t FROM UnifiedToken t WHERE t.expirationDate < :date AND t.tokenType = 'TWO_FACTOR'")
    List<UnifiedToken> findByExpirationDateBefore(LocalDateTime date);

    @Query("SELECT t FROM UnifiedToken t WHERE t.verificationToken = :verificationToken AND t.tokenType = 'TWO_FACTOR'")
    Optional<UnifiedToken> findByVerificationToken(String verificationToken);

    @Modifying
    @Query("DELETE FROM UnifiedToken t WHERE t.verificationToken = :verificationToken AND t.tokenType = 'TWO_FACTOR'")
    void deleteByVerificationToken(String verificationToken);
} 