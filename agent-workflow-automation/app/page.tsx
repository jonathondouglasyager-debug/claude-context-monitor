
import fs from 'node:fs';
import path from 'node:path';
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Activity, CheckCircle, AlertCircle, Clock, FileText, ListTodo } from "lucide-react";

// Types
interface Issue {
  id: string;
  type: string;
  timestamp: string;
  description: string;
  status: string;
  tool_name: string;
}

interface Task {
  id: string;
  title: string;
  priority: string;
  complexity: string;
  status: string;
  description: string;
}

// Data fetching
function getIssues(): Issue[] {
  try {
    const filePath = path.join(process.cwd(), 'data/issues.jsonl');
    if (!fs.existsSync(filePath)) return [];
    
    const fileContent = fs.readFileSync(filePath, 'utf-8');
    return fileContent
      .split('\n')
      .filter(line => line.trim())
      .map(line => {
        try {
          return JSON.parse(line);
        } catch (e) {
          return null;
        }
      })
      .filter((item): item is Issue => item !== null)
      .reverse(); // Newest first
  } catch (e) {
    console.error("Failed to read issues", e);
    return [];
  }
}

function getConvergenceReport(): string {
  try {
    const filePath = path.join(process.cwd(), 'convergence/convergence.md');
    if (!fs.existsSync(filePath)) return "No convergence report found.";
    return fs.readFileSync(filePath, 'utf-8');
  } catch (e) {
    return "Error reading convergence report.";
  }
}

function getTasks(): Task[] {
  try {
    const filePath = path.join(process.cwd(), 'convergence/tasks.json');
    if (!fs.existsSync(filePath)) return [];
    return JSON.parse(fs.readFileSync(filePath, 'utf-8'));
  } catch (e) {
    console.error("Failed to read tasks", e);
    return [];
  }
}

export default function Dashboard() {
  const issues = getIssues();
  const convergenceReport = getConvergenceReport();
  const tasks = getTasks();

  const stats = {
    total: issues.length,
    converged: issues.filter(i => i.status === 'converged').length,
    pending: issues.filter(i => ['captured', 'researching', 'debating'].includes(i.status)).length,
    tasks: tasks.length
  };

  return (
    <div className="flex min-h-screen w-full flex-col bg-muted/40">
      <div className="flex flex-col sm:gap-4 sm:py-4 sm:pl-14">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-4 border-b bg-background px-4 sm:static sm:h-auto sm:border-0 sm:bg-transparent sm:px-6">
          <h1 className="text-2xl font-semibold tracking-tight">Convergence Engine Dashboard</h1>
        </header>
        <main className="grid flex-1 items-start gap-4 p-4 sm:px-6 sm:py-0 md:gap-8">
          
          {/* Stats Cards */}
          <div className="grid gap-4 md:grid-cols-2 md:gap-8 lg:grid-cols-4">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Total Issues</CardTitle>
                <Activity className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{stats.total}</div>
                <p className="text-xs text-muted-foreground">Captured pipeline events</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Converged</CardTitle>
                <CheckCircle className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{stats.converged}</div>
                <p className="text-xs text-muted-foreground">Successfully analyzed</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Pending</CardTitle>
                <Clock className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{stats.pending}</div>
                <p className="text-xs text-muted-foreground">Needs research/debate</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Generated Tasks</CardTitle>
                <ListTodo className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{stats.tasks}</div>
                <p className="text-xs text-muted-foreground">Actionable items</p>
              </CardContent>
            </Card>
          </div>

          <Tabs defaultValue="issues" className="w-full">
            <div className="flex items-center">
              <TabsList>
                <TabsTrigger value="issues">Issues</TabsTrigger>
                <TabsTrigger value="convergence">Convergence Report</TabsTrigger>
                <TabsTrigger value="tasks">Tasks</TabsTrigger>
              </TabsList>
            </div>
            
            {/* Issues Tab */}
            <TabsContent value="issues">
              <Card>
                <CardHeader>
                  <CardTitle>Issue Log</CardTitle>
                  <CardDescription>
                    Recent issues captured by the pipeline.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>ID</TableHead>
                        <TableHead>Type</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Description</TableHead>
                        <TableHead className="text-right">Timestamp</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {issues.map((issue) => (
                        <TableRow key={issue.id}>
                          <TableCell className="font-medium">{issue.id}</TableCell>
                          <TableCell>
                            <Badge variant="outline">{issue.type}</Badge>
                          </TableCell>
                          <TableCell>
                            <Badge variant={issue.status === 'converged' ? 'default' : 'secondary'}>
                              {issue.status}
                            </Badge>
                          </TableCell>
                          <TableCell className="max-w-md truncate" title={issue.description}>
                            {issue.description}
                          </TableCell>
                          <TableCell className="text-right text-muted-foreground">
                            {new Date(issue.timestamp).toLocaleString()}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            </TabsContent>

            {/* Convergence Report Tab */}
            <TabsContent value="convergence">
              <Card>
                <CardHeader>
                  <CardTitle>Latest Convergence Report</CardTitle>
                  <CardDescription>Synthesized findings from the arbiter agent.</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="p-4 bg-slate-50 rounded-md border text-sm font-mono whitespace-pre-wrap dark:bg-slate-950">
                    {convergenceReport}
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            {/* Tasks Tab */}
            <TabsContent value="tasks">
              <Card>
                <CardHeader>
                  <CardTitle>Actionable Tasks</CardTitle>
                  <CardDescription>Tasks generated from improved convergence.</CardDescription>
                </CardHeader>
                <CardContent>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Priority</TableHead>
                        <TableHead>Task</TableHead>
                        <TableHead>Complexity</TableHead>
                        <TableHead>Description</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {tasks.map((task) => (
                        <TableRow key={task.id}>
                          <TableCell>
                            <Badge variant={task.priority === 'P0' || task.priority === 'P1' ? 'destructive' : 'default'}>
                              {task.priority}
                            </Badge>
                          </TableCell>
                          <TableCell className="font-medium">{task.title}</TableCell>
                          <TableCell>{task.complexity}</TableCell>
                          <TableCell>{task.description}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            </TabsContent>

          </Tabs>
        </main>
      </div>
    </div>
  );
}
