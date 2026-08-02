/**
 * PaperLens 日志系统
 * 统一管理前后端日志，输出到用户数据目录
 */

const path = require('path');
const fs = require('fs');
const { app } = require('electron');

// 确保日志目录存在
function ensureLogDirectory() {
    const logDir = getLogDirectory();
    if (!fs.existsSync(logDir)) {
        fs.mkdirSync(logDir, { recursive: true });
    }
    return logDir;
}

// 获取日志目录
function getLogDirectory() {
    return path.join(app.getPath('userData'), 'logs');
}

// 获取日志文件路径
function getLogFilePath(type = 'main') {
    const date = new Date().toISOString().split('T')[0];
    const logDir = getLogDirectory();
    return path.join(logDir, `${type}-${date}.log`);
}

// 格式化日志消息
function formatMessage(level, context, message, data = null) {
    const timestamp = new Date().toISOString();
    const contextStr = context ? `[${context}] ` : '';
    const dataStr = data ? ` ${JSON.stringify(data)}` : '';
    return `[${timestamp}] [${level.toUpperCase()}] ${contextStr}${message}${dataStr}\n`;
}

// 写入日志到文件
function writeToFile(type, level, context, message, data) {
    try {
        const logPath = getLogFilePath(type);
        ensureLogDirectory();
        const formatted = formatMessage(level, context, message, data);
        fs.appendFileSync(logPath, formatted);
    } catch (error) {
        console.error('Failed to write log:', error);
    }
}

// 日志级别
const LogLevel = {
    DEBUG: 'debug',
    INFO: 'info',
    WARN: 'warn',
    ERROR: 'error'
};

/**
 * 创建日志记录器
 * @param {string} type - 日志类型 (main, backend, frontend 等)
 * @param {string} context - 日志上下文
 */
function createLogger(type, context = '') {
    return {
        debug: (message, data) => {
            const msg = formatMessage(LogLevel.DEBUG, context, message, data);
            console.debug(msg);
            writeToFile(type, LogLevel.DEBUG, context, message, data);
        },
        info: (message, data) => {
            const msg = formatMessage(LogLevel.INFO, context, message, data);
            console.log(msg);
            writeToFile(type, LogLevel.INFO, context, message, data);
        },
        warn: (message, data) => {
            const msg = formatMessage(LogLevel.WARN, context, message, data);
            console.warn(msg);
            writeToFile(type, LogLevel.WARN, context, message, data);
        },
        error: (message, data) => {
            const msg = formatMessage(LogLevel.ERROR, context, message, data);
            console.error(msg);
            writeToFile(type, LogLevel.ERROR, context, message, data);
        }
    };
}

/**
 * 清理旧日志文件（保留最近 7 天）
 */
function cleanOldLogs() {
    try {
        const logDir = getLogDirectory();
        if (!fs.existsSync(logDir)) return;

        const files = fs.readdirSync(logDir);
        const now = Date.now();
        const sevenDays = 7 * 24 * 60 * 60 * 1000;

        files.forEach(file => {
            const filePath = path.join(logDir, file);
            const stats = fs.statSync(filePath);
            if (now - stats.mtimeMs > sevenDays) {
                fs.unlinkSync(filePath);
                console.log(`[Logger] Deleted old log: ${file}`);
            }
        });
    } catch (error) {
        console.error('[Logger] Failed to clean old logs:', error);
    }
}

/**
 * 获取所有日志文件列表
 */
function getLogFiles() {
    try {
        const logDir = getLogDirectory();
        if (!fs.existsSync(logDir)) return [];
        return fs.readdirSync(logDir)
            .filter(f => f.endsWith('.log'))
            .sort()
            .reverse();
    } catch (error) {
        console.error('[Logger] Failed to get log files:', error);
        return [];
    }
}

/**
 * 读取日志文件内容
 */
function readLogFile(filename) {
    try {
        const logDir = getLogDirectory();
        const filePath = path.join(logDir, filename);
        return fs.readFileSync(filePath, 'utf-8');
    } catch (error) {
        console.error('[Logger] Failed to read log file:', error);
        return null;
    }
}

module.exports = {
    createLogger,
    getLogDirectory,
    getLogFilePath,
    getLogFiles,
    readLogFile,
    cleanOldLogs,
    writeToFile,
    LogLevel
};
