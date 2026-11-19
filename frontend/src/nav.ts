// Разделы, которые на телефоне живут в «Ещё». Все уже в новом интерфейсе.
export const MORE = [
  { to: "/recipes", label: "Рецепты", icon: "recipe", next: true },
  { to: "/catalog", label: "Продукты", icon: "catalog", next: true },
  { to: "/money", label: "Деньги", icon: "money", next: true },
  { to: "/family", label: "Семья", icon: "family", next: true },
] as const;
