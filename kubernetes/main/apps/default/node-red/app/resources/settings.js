module.exports = {
  flowFile: "flows.json",
  credentialSecret: process.env.NODE_RED_CREDENTIAL_SECRET,
  flowFilePretty: true,

  // adminAuth: {
  //   type: "strategy",
  //   strategy: {
  //     name: "openidconnect",
  //     autoLogin: true,
  //     label: "Sign in",
  //     icon: "fa-cloud",
  //     strategy: require("passport-openidconnect").Strategy,
  //     options: {
  //       issuer: "https://auth.mcgrath.nz",
  //       authorizationURL: "https://auth.mcgrath.nz/api/oidc/authorization",
  //       tokenURL: "https://auth.mcgrath.nz/api/oidc/token",
  //       userInfoURL: "https://auth.mcgrath.nz/api/oidc/userinfo",
  //       clientID: "nodered",
  //       clientSecret: process.env.NODERED_OAUTH_CLIENT_SECRET,
  //       callbackURL: "https://nodered.mcgrath.nz/auth/strategy/callback",
  //       scope: ["email", "profile", "openid"],
  //       proxy: true,
  //       verify: function (issuer, profile, done) {
  //         done(null, profile)
  //       },
  //     },
  //   },
  //   users: [{ username: "sean", permissions: ["*"] }],
  // },

  uiPort: process.env.PORT || 1880,

  diagnostics: {
    enabled: true,
    ui: true,
  },

  runtimeState: {
    enabled: false,
    ui: false,
  },

  logging: {
    console: {
      level: "info",
      metrics: false,
      audit: false,
    },
  },

  contextStorage: {
    default: {
      module: "localfilesystem",
    },
  },

  exportGlobalContextKeys: false,

  externalModules: {},

  editorTheme: {
    tours: false,

    projects: {
      enabled: false,
      workflow: {
        mode: "manual",
      },
    },

    codeEditor: {
      lib: "monaco",
      options: {},
    },
  },

  functionExternalModules: true,
  functionGlobalContext: {},

  debugMaxLength: 1000,

  mqttReconnectTime: 15000,
  serialReconnectTime: 15000,
}
