import { describe, it, expect, beforeEach } from 'vitest';
import { WsManager } from './ws-manager';

describe('WsManager', () => {
  let manager: WsManager;

  beforeEach(() => {
    manager = new WsManager();
  });

  it('starts disconnected', () => {
    expect(manager.connected).toBe(false);
  });

  it('tracks subscriptions', () => {
    const handler = () => {};
    const sub = manager.subscribe('test-channel', handler);
    expect(sub).toHaveProperty('unsubscribe');
    sub.unsubscribe();
  });

  it('allows multiple subscriptions to same channel', () => {
    const handler1 = () => {};
    const handler2 = () => {};
    const sub1 = manager.subscribe('ch', handler1);
    const sub2 = manager.subscribe('ch', handler2);
    sub1.unsubscribe();
    sub2.unsubscribe();
  });

  it('disconnect sets connected to false', () => {
    manager.disconnect();
    expect(manager.connected).toBe(false);
  });
});
