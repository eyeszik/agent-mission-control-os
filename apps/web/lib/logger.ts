import { createLogger, type Logger } from '@amc/logger';
import { getAppConfig } from './config';

let instance: Logger | null = null;

/** App-wide logger (level from NEXT_PUBLIC_LOG_LEVEL, default info). */
export function getLogger(): Logger {
  instance ??= createLogger({ name: 'amc-web', level: getAppConfig().logLevel });
  return instance;
}
