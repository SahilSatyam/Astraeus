'use client';

import { useEffect } from 'react';

type KeyCombo = {
  key: string;
  ctrl?: boolean;
  meta?: boolean;
  shift?: boolean;
  alt?: boolean;
};

/**
 * Register a global keyboard shortcut.
 * Automatically handles both Ctrl (Windows) and Meta (Mac).
 */
export function useKeyboardShortcut(combo: KeyCombo, handler: () => void) {
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const matchKey = e.key.toLowerCase() === combo.key.toLowerCase();
      const matchCtrl = combo.ctrl ? e.ctrlKey || e.metaKey : true;
      const matchShift = combo.shift ? e.shiftKey : !e.shiftKey;
      const matchAlt = combo.alt ? e.altKey : !e.altKey;

      if (matchKey && matchCtrl && matchShift && matchAlt) {
        e.preventDefault();
        handler();
      }
    }

    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [combo, handler]);
}
