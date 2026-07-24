import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { HeadContent, Link, Scripts, createRootRoute } from '@tanstack/react-router'
import { TanStackRouterDevtoolsPanel } from '@tanstack/react-router-devtools'
import { TanStackDevtools } from '@tanstack/react-devtools'

import appCss from '../styles.css?url'

const queryClient = new QueryClient()

export const Route = createRootRoute({
  head: () => ({
    meta: [
      {
        charSet: 'utf-8',
      },
      {
        name: 'viewport',
        content: 'width=device-width, initial-scale=1',
      },
      {
        title: 'Lab Console',
      },
    ],
    links: [
      {
        rel: 'stylesheet',
        href: appCss,
      },
    ],
  }),
  shellComponent: RootDocument,
})

function RootDocument({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <HeadContent />
      </head>
      <body>
        <QueryClientProvider client={queryClient}>
          <nav className="flex items-center gap-4 border-b px-6 py-3 text-sm">
            <Link to="/" className="font-semibold">
              Lab Console
            </Link>
            <Link to="/robot" className="text-muted-foreground hover:text-foreground">
              Robot
            </Link>
            <Link to="/datasets" className="text-muted-foreground hover:text-foreground">
              Datasets
            </Link>
            <Link to="/trainings" className="text-muted-foreground hover:text-foreground">
              Trainings
            </Link>
            <a
              href="/api/docs"
              className="ml-auto text-muted-foreground hover:text-foreground"
              target="_blank"
              rel="noreferrer"
            >
              API docs
            </a>
          </nav>
          {children}
        </QueryClientProvider>
        <TanStackDevtools
          config={{
            position: 'bottom-right',
          }}
          plugins={[
            {
              name: 'Tanstack Router',
              render: <TanStackRouterDevtoolsPanel />,
            },
          ]}
        />
        <Scripts />
      </body>
    </html>
  )
}
