-- Runs once on first MySQL container initialization.
-- The image already created the development database and the `meridian` user
-- with privileges on it. Here we add the dedicated test database and grant the
-- development account only the privileges it needs on it. Django creates and
-- drops the test schema during test runs, so the account needs full rights on
-- the meridian_test.* namespace but nothing global.
--
-- Assumes MYSQL_USER=meridian (see .env.example). If you change the user name,
-- update the GRANT below accordingly.

CREATE DATABASE IF NOT EXISTS `meridian_test`
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_0900_ai_ci;

GRANT ALL PRIVILEGES ON `meridian_test`.* TO 'meridian'@'%';

FLUSH PRIVILEGES;
