package com.trading.easytradify.auth.repository;

import com.trading.easytradify.auth.entities.UnifiedToken;
import com.trading.easytradify.auth.entities.enums.TokenType;
import jakarta.transaction.Transactional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

@Repository
public interface UnifiedTokenRepository extends JpaRepository<UnifiedToken, Long> {

    // ===== JWT TOKEN METHODS (DEPRECATED - TO BE REMOVED AFTER MIGRATION) =====

    @Query(value = """
      select t from UnifiedToken t inner join User u\s
      on t.user.id = u.id\s
      where u.id = :id and t.tokenType = 'JWT' and (t.expired = false or t.revoked = false)\s
      """)
    List<UnifiedToken> findAllValidTokenByUser(Integer id);

    @Query(value = """
      select COUNT(t) from UnifiedToken t inner join User u\s
      on t.user.id = u.id\s
      where u.id = :id and t.tokenType = 'JWT' and (t.expired = false or t.revoked = false)\s
      """)
    Integer findCountAllValidTokenByUser(Integer id);

    @Query("SELECT t FROM UnifiedToken t WHERE t.token = :token AND t.tokenType = 'JWT'")
    Optional<UnifiedToken> findByToken(String token);

    @Modifying
    @Query("DELETE FROM UnifiedToken t WHERE t.user.id = :userId AND t.tokenType = 'JWT'")
    void deleteAllByUserId(@Param("userId") Integer userId);

    @Modifying
    @Transactional
    @Query("DELETE FROM UnifiedToken t WHERE t.user.email = :email AND t.tokenType = 'JWT'")
    void deleteAllByUserEmail(@Param("email") String email);

    @Query("SELECT t FROM UnifiedToken t WHERE t.user.id = :userId AND t.ipHash = :ipHash AND t.tokenType = 'JWT'")
    Optional<UnifiedToken> findValidTokenForUserAndIp(
            @Param("userId") Integer userId,
            @Param("ipHash") String ipHash
    );

    @Query("SELECT t FROM UnifiedToken t WHERE t.token = :token AND t.ipHash = :ipHash AND t.tokenType = 'JWT'")
    Optional<UnifiedToken> findByTokenAndIpHash(String token, String ipHash);

    // ===== OAUTH2 TOKEN METHODS (NEW) =====

    /**
     * Find OAuth2 token (access or refresh) by token value
     */
    @Query("SELECT t FROM UnifiedToken t WHERE t.token = :token AND t.tokenType IN ('OAUTH2_ACCESS', 'OAUTH2_REFRESH')")
    Optional<UnifiedToken> findOAuth2TokenByToken(@Param("token") String token);

    /**
     * Find OAuth2 token with IP validation
     */
    @Query("SELECT t FROM UnifiedToken t WHERE t.token = :token AND t.ipHash = :ipHash AND t.tokenType IN ('OAUTH2_ACCESS', 'OAUTH2_REFRESH')")
    Optional<UnifiedToken> findOAuth2TokenByTokenAndIpHash(@Param("token") String token, @Param("ipHash") String ipHash);

    /**
     * Find all active OAuth2 tokens for a user (not revoked, not expired)
     */
    @Query("SELECT t FROM UnifiedToken t WHERE t.user.id = :userId AND t.tokenType IN ('OAUTH2_ACCESS', 'OAUTH2_REFRESH') AND t.revoked = false AND t.expired = false AND t.expirationDate > :now")
    List<UnifiedToken> findActiveOAuth2TokensByUser(@Param("userId") Integer userId, @Param("now") LocalDateTime now);

    /**
     * Find all active OAuth2 access tokens for a user
     */
    @Query("SELECT t FROM UnifiedToken t WHERE t.user.id = :userId AND t.tokenType = 'OAUTH2_ACCESS' AND t.revoked = false AND t.expired = false AND t.expirationDate > :now")
    List<UnifiedToken> findActiveOAuth2AccessTokensByUser(@Param("userId") Integer userId, @Param("now") LocalDateTime now);

    /**
     * Find all active OAuth2 refresh tokens for a user
     */
    @Query("SELECT t FROM UnifiedToken t WHERE t.user.id = :userId AND t.tokenType = 'OAUTH2_REFRESH' AND t.revoked = false AND t.expired = false AND t.expirationDate > :now")
    List<UnifiedToken> findActiveOAuth2RefreshTokensByUser(@Param("userId") Integer userId, @Param("now") LocalDateTime now);

    /**
     * Revoke all OAuth2 tokens for a user (logout from all devices)
     */
    @Modifying
    @Transactional
    @Query("UPDATE UnifiedToken t SET t.revoked = true, t.expired = true WHERE t.user.id = :userId AND t.tokenType IN ('OAUTH2_ACCESS', 'OAUTH2_REFRESH')")
    void revokeAllOAuth2TokensByUser(@Param("userId") Integer userId);

    /**
     * Revoke a specific OAuth2 token
     */
    @Modifying
    @Transactional
    @Query("UPDATE UnifiedToken t SET t.revoked = true, t.expired = true WHERE t.token = :token AND t.tokenType IN ('OAUTH2_ACCESS', 'OAUTH2_REFRESH')")
    void revokeOAuth2Token(@Param("token") String token);

    /**
     * Delete expired OAuth2 tokens
     */
    @Modifying
    @Transactional
    @Query("DELETE FROM UnifiedToken t WHERE t.expirationDate < :date AND t.tokenType IN ('OAUTH2_ACCESS', 'OAUTH2_REFRESH')")
    void deleteExpiredOAuth2Tokens(@Param("date") LocalDateTime date);

    // ===== PASSWORD RESET TOKEN METHODS (from PasswordResetTokenRepository) =====

    @Query("SELECT t FROM UnifiedToken t WHERE t.token = :token AND t.tokenType = 'PASSWORD_RESET'")
    Optional<UnifiedToken> findPasswordResetTokenByToken(String token);

    @Modifying
    @Query("DELETE FROM UnifiedToken t WHERE t.userEmail = :email AND t.tokenType = 'PASSWORD_RESET'")
    void deletePasswordResetTokenByUserEmail(String email);

    @Query("SELECT t FROM UnifiedToken t WHERE t.userEmail = :userEmail AND t.tokenType = 'PASSWORD_RESET' ORDER BY t.creationDate DESC")
    Optional<UnifiedToken> findTopPasswordResetTokenByUserEmailOrderByCreationDateDesc(String userEmail);

    // ===== TWO FACTOR AUTH TOKEN METHODS (from TwoFactorAuthRepository) =====

    @Query("SELECT t FROM UnifiedToken t WHERE t.token = :token AND t.userEmail = :userEmail AND t.tokenType = 'TWO_FACTOR'")
    Optional<UnifiedToken> findByTokenAndUserEmail(String token, String userEmail);

    @Modifying
    @Query("DELETE FROM UnifiedToken t WHERE t.userEmail = :email AND t.tokenType = 'TWO_FACTOR'")
    void deleteTwoFactorTokenByUserEmail(String email);

    @Query("SELECT t FROM UnifiedToken t WHERE t.userEmail = :userEmail AND t.tokenType = 'TWO_FACTOR' ORDER BY t.creationDate DESC")
    Optional<UnifiedToken> findTopTwoFactorTokenByUserEmailOrderByCreationDateDesc(String userEmail);

    @Query("SELECT t FROM UnifiedToken t WHERE t.expirationDate < :date AND t.tokenType = 'TWO_FACTOR'")
    List<UnifiedToken> findExpiredTwoFactorTokensByExpirationDateBefore(LocalDateTime date);

    @Query("SELECT t FROM UnifiedToken t WHERE t.verificationToken = :verificationToken AND t.tokenType = 'TWO_FACTOR'")
    Optional<UnifiedToken> findByVerificationToken(String verificationToken);

    @Modifying
    @Query("DELETE FROM UnifiedToken t WHERE t.verificationToken = :verificationToken AND t.tokenType = 'TWO_FACTOR'")
    void deleteByVerificationToken(String verificationToken);

    // ===== COUNT METHODS =====

    Long countByUserEmailAndTokenTypeAndExpiredFalseAndRevokedFalse(
            String email, TokenType tokenType);

    /**
     * Count active OAuth2 tokens for a user
     */
    @Query("SELECT COUNT(t) FROM UnifiedToken t WHERE t.user.id = :userId AND t.tokenType IN ('OAUTH2_ACCESS', 'OAUTH2_REFRESH') AND t.revoked = false AND t.expired = false AND t.expirationDate > :now")
    Long countActiveOAuth2TokensByUser(@Param("userId") Integer userId, @Param("now") LocalDateTime now);

    // ===== GENERIC METHODS FOR ALL TOKEN TYPES =====

    @Query("SELECT t FROM UnifiedToken t WHERE t.token = :token AND t.tokenType = :tokenType")
    Optional<UnifiedToken> findByTokenAndType(String token, TokenType tokenType);

    @Query("SELECT t FROM UnifiedToken t WHERE t.userEmail = :userEmail AND t.tokenType = :tokenType")
    List<UnifiedToken> findByUserEmailAndType(String userEmail, TokenType tokenType);

    @Modifying
    @Query("DELETE FROM UnifiedToken t WHERE t.userEmail = :email AND t.tokenType = :tokenType")
    void deleteByUserEmailAndType(String email, TokenType tokenType);

    @Query("SELECT t FROM UnifiedToken t WHERE t.expirationDate < :date AND t.tokenType = :tokenType")
    List<UnifiedToken> findExpiredTokensByTypeAndDate(TokenType tokenType, LocalDateTime date);

    // ===== TOKEN BINDING METHODS (for OAuth2 IP/UA validation) =====

    @Query("SELECT t FROM UnifiedToken t WHERE t.token = :token AND t.ipHash = :ipHash AND t.userAgentHash = :userAgentHash AND t.tokenType IN ('OAUTH2_ACCESS', 'OAUTH2_REFRESH')")
    Optional<UnifiedToken> findOAuth2TokenByBinding(
            @Param("token") String token,
            @Param("ipHash") String ipHash,
            @Param("userAgentHash") String userAgentHash
    );

    @Query("SELECT t FROM UnifiedToken t WHERE t.token = :token AND t.ipHash = :ipHash AND t.tokenType = :tokenType")
    Optional<UnifiedToken> findByTokenAndIpHashAndTokenType(
            @Param("token") String token,
            @Param("ipHash") String ipHash,
            @Param("tokenType") TokenType tokenType
    );
}