import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import ar from "./ar.json";
import en from "./en.json";

export const LANGUAGES = ["en", "ar"] as const;
export type Language = (typeof LANGUAGES)[number];

const STORAGE_KEY = "daleel.lang";

function isLanguage(value: unknown): value is Language {
  return LANGUAGES.includes(value as Language);
}

function initialLanguage(): Language {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (isLanguage(stored)) return stored;
  } catch {
    // storage unavailable (private mode); fall through to the browser language
  }
  return navigator.language.toLowerCase().startsWith("ar") ? "ar" : "en";
}

/** Mirrors the active language onto <html> so CSS logical properties flip for RTL. */
function applyToDocument(lng: string): void {
  document.documentElement.lang = lng;
  document.documentElement.dir = i18n.dir(lng);
}

export function setLanguage(lng: Language): void {
  void i18n.changeLanguage(lng);
  try {
    localStorage.setItem(STORAGE_KEY, lng);
  } catch {
    // not persisted; the choice still applies for this session
  }
}

i18n.on("languageChanged", applyToDocument);

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, ar: { translation: ar } },
  lng: initialLanguage(),
  fallbackLng: "en",
  supportedLngs: LANGUAGES,
  interpolation: { escapeValue: false }, // React escapes
});
applyToDocument(i18n.language);

export default i18n;
