export interface BackgroundTaskEvent {
  runId: string;
  nodeId: string;
  payload: any;
  timestamp: string;
}

export interface WebhookEvent {
  type: string;
  data: any;
}
