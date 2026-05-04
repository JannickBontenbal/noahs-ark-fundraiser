window.NAF_CONFIG = {
  SUPABASE_URL: "https://your-project.supabase.co",
  SUPABASE_ANON_KEY: "sb_publishable_your_publishable_key",
  SUPABASE_PUBLISHABLE_KEY: "sb_publishable_your_publishable_key",
  SUPABASE_SERVICE_KEY: "",
  ADMIN_API_URL: "",
  ADMIN_PASSWORD_HASH: "",
  GOAL_EUR: 10000,
  TARGET_DATE: "2027-02-01",
  IBAN: "NL00 BANK 0000 0000 00",
  IBAN_NAME: "Stichting naam",
  TIKKIE_URL: "https://tikkie.me/pay/example",
  STRIPE_PUBLISHABLE_KEY: "pk_test_your_publishable_key",
  STRIPE_ENABLED: false,
  STRIPE_FEE_CENTS: 50,
  ACTIONS: [
    {
      title: "Sponsorloop",
      description: "Leerlingen laten zich sponsoren per ronde en verzamelen zo direct donaties voor de reis en het project.",
      status_label: "Status",
      status: "Actief",
      tags: ["Loopt nu", "Schoolactie"],
      variant: "featured"
    },
    {
      title: "Actiemarkt",
      description: "Een middag met kleine verkoopacties, eten, drinken en creatieve manieren om geld op te halen.",
      status_label: "Status",
      status: "In voorbereiding",
      tags: ["Binnenkort", "Samen"],
      variant: "coral"
    }
  ]
};
