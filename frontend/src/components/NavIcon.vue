<template>
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <template v-if="name === 'dashboard'">
      <rect x="3" y="3" width="7.5" height="7.5" rx="1.5" />
      <rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5" />
      <rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5" />
      <rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5" />
    </template>
    <template v-else-if="name === 'accounts'">
      <circle cx="9" cy="8" r="3.4" />
      <path d="M3.5 20c0-3 2.5-5 5.5-5s5.5 2 5.5 5" />
      <path d="M16 8.5a3 3 0 1 0 0-0.01" />
      <path d="M16.5 15.2c2.4.4 4 2 4 4.6" />
    </template>
    <template v-else-if="name === 'plans'">
      <rect x="5" y="4" width="14" height="17" rx="2" />
      <path d="M9 4V2.8h6V4" />
      <path d="m8.6 13 2.3 2.3 4.6-4.6" />
    </template>
    <template v-else-if="name === 'research'">
      <path d="M9 3h6" />
      <path d="M10 3v5.2l-5 8.5A2.8 2.8 0 0 0 7.4 21h9.2a2.8 2.8 0 0 0 2.4-4.3l-5-8.5V3" />
      <path d="M7.2 15h9.6" />
    </template>
    <template v-else-if="name === 'symbol'">
      <path d="M8 5v3M8 16v3M8 8h-2.2v8H8V8ZM8 8h2.2v8H8" />
      <path d="M16 4v3M16 17v3M16 7h-2.2v10H16V7ZM16 7h2.2v10H16" />
    </template>
    <template v-else-if="name === 'risk'">
      <path d="M12 3 5 6v5c0 4.5 3 8 7 10 4-2 7-5.5 7-10V6l-7-3Z" />
      <path d="M12 8v4.5" />
      <circle cx="12" cy="15.6" r="0.4" />
    </template>
    <template v-else-if="name === 'reports'">
      <path d="M6.5 3h8L19 7.5V21h-12.5V3Z" />
      <path d="M14 3v5h5" />
      <path d="M9.5 13.5h5.5M9.5 17h5.5" />
    </template>
    <template v-else>
      <circle cx="12" cy="12" r="8" />
    </template>
  </svg>
</template>

<script setup>
defineProps({
  name: { type: String, required: true },
});
</script>
