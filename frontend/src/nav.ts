// Разделы, которые на телефоне живут в «Ещё». next — уже в новом интерфейсе, иначе ссылка в старый /app/.
export const MORE = [
  { to: "/recipes", label: "Рецепты", icon: "recipe", next: true },
  { to: "/catalog", label: "Продукты", icon: "catalog", next: true },
  { to: "/app/#/money", label: "Деньги", icon: "money" },
  { to: "/family", label: "Семья", icon: "family", next: true },
] as const;
